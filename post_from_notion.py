"""Notion「発信の下書き」から X へ投稿するスクリプト

状態が「確認中」で、形式が「短文投稿」「連続投稿」の下書きだけを投稿する。
投稿できたら状態を「投稿済み」にし、「投稿のリンク」に投稿先を残す。

本文の決まり:
- ページ本文の段落をそのまま投稿文にする
- 末尾の「(128字)」のような字数メモは投稿しない
- 連続投稿は、区切り線(---)で1本ずつに分ける

DRY_RUN=1 を付けると、投稿もNotionの更新もせず、投稿予定の文面だけ表示する。
"""

import os
import re
import sys
import time

import requests

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
DEFAULT_DATABASE_ID = "590941f10a7b4fd48281660c4f9d0057"

STATUS_PROP = "状態"
STATUS_READY = "確認中"
STATUS_DONE = "投稿済み"
FORMAT_PROP = "形式"
POSTABLE_FORMATS = {"短文投稿", "連続投稿"}
LINK_PROP = "投稿のリンク"
TITLE_PROP = "題名"

X_MAX_WEIGHT = 280  # 全角は1字で2と数えるので、全角140字にあたる
SLEEP_BETWEEN_POSTS_SEC = 2
CHAR_COUNT_NOTE = re.compile(r"^[((]\s*\d+\s*字\s*[))]$")
TEXT_BLOCK_TYPES = {
    "paragraph",
    "quote",
    "bulleted_list_item",
    "numbered_list_item",
    "heading_1",
    "heading_2",
    "heading_3",
}


def x_weight(text: str) -> int:
    """X の数え方での長さ(半角1、全角2)。"""
    total = 0
    for ch in text:
        cp = ord(ch)
        light = (
            cp <= 0x10FF
            or 0x2000 <= cp <= 0x200D
            or 0x2010 <= cp <= 0x201F
            or 0x2032 <= cp <= 0x2037
        )
        total += 1 if light else 2
    return total


def blocks_to_posts(blocks: list[dict]) -> list[str]:
    """Notion のブロック一覧を、投稿文のリストにする(区切り線で分割)。"""
    groups: list[list[str]] = [[]]
    for block in blocks:
        kind = block.get("type")
        if kind == "divider":
            groups.append([])
            continue
        if kind not in TEXT_BLOCK_TYPES:
            continue
        rich = block.get(kind, {}).get("rich_text", [])
        text = "".join(part.get("plain_text", "") for part in rich).strip()
        if not text or CHAR_COUNT_NOTE.match(text):
            continue
        groups[-1].append(text)

    posts = []
    for paragraphs in groups:
        if not paragraphs:
            continue
        text = "\n\n".join(paragraphs)
        if x_weight(text) > X_MAX_WEIGHT:
            # 空行のぶんで字数を超えるときは、改行1つに詰める
            text = "\n".join(paragraphs)
        posts.append(text)
    return posts


class Notion:
    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            }
        )

    def _request(self, method: str, path: str, **kwargs) -> dict:
        res = self.session.request(method, f"{NOTION_API}{path}", timeout=30, **kwargs)
        if not res.ok:
            raise RuntimeError(f"Notion {method} {path}: {res.status_code} {res.text[:300]}")
        return res.json()

    def ready_pages(self, database_id: str) -> list[dict]:
        pages, cursor = [], None
        while True:
            body = {
                "filter": {"property": STATUS_PROP, "status": {"equals": STATUS_READY}},
                "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
            }
            if cursor:
                body["start_cursor"] = cursor
            data = self._request("POST", f"/databases/{database_id}/query", json=body)
            pages.extend(data["results"])
            if not data.get("has_more"):
                return pages
            cursor = data["next_cursor"]

    def blocks(self, page_id: str) -> list[dict]:
        blocks, cursor = [], None
        while True:
            params = {"page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = self._request("GET", f"/blocks/{page_id}/children", params=params)
            blocks.extend(data["results"])
            if not data.get("has_more"):
                return blocks
            cursor = data["next_cursor"]

    def mark_posted(self, page_id: str, link: str) -> None:
        self._request(
            "PATCH",
            f"/pages/{page_id}",
            json={
                "properties": {
                    STATUS_PROP: {"status": {"name": STATUS_DONE}},
                    LINK_PROP: {"url": link},
                }
            },
        )


def page_title(page: dict) -> str:
    parts = page["properties"].get(TITLE_PROP, {}).get("title", [])
    return "".join(p.get("plain_text", "") for p in parts) or "(題名なし)"


def page_format(page: dict) -> str:
    select = page["properties"].get(FORMAT_PROP, {}).get("select")
    return select["name"] if select else ""


def build_x_client():
    import tweepy

    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def main() -> int:
    dry_run = os.environ.get("DRY_RUN", "") not in ("", "0", "false")
    database_id = os.environ.get("NOTION_DATABASE_ID") or DEFAULT_DATABASE_ID
    needed = ["NOTION_TOKEN"]
    if not dry_run:
        needed += ["X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET"]
    missing = [name for name in needed if not os.environ.get(name)]
    if missing:
        # 鍵の登録前は、失敗の通知を出し続けないよう静かに終わる
        print(f"[SETUP] まだ登録されていない鍵があります: {', '.join(missing)}")
        print("[SETUP] GitHub の Settings → Secrets and variables → Actions に登録してください")
        return 0

    notion = Notion(os.environ["NOTION_TOKEN"])

    pages = notion.ready_pages(database_id)
    if not pages:
        print("[DONE] 「確認中」の下書きはありません")
        return 0

    x_client = None if dry_run else build_x_client()
    posted = skipped = failed = 0

    for page in pages:
        title = page_title(page)
        fmt = page_format(page)
        if fmt not in POSTABLE_FORMATS:
            print(f"[SKIP] {title}: 形式「{fmt}」はXに投稿しません")
            skipped += 1
            continue

        posts = blocks_to_posts(notion.blocks(page["id"]))
        if not posts:
            print(f"[SKIP] {title}: 本文が空です", file=sys.stderr)
            failed += 1
            continue
        too_long = [p for p in posts if x_weight(p) > X_MAX_WEIGHT]
        if too_long:
            print(
                f"[SKIP] {title}: 字数を超えています(全角140字まで): {too_long[0][:30]!r}",
                file=sys.stderr,
            )
            failed += 1
            continue
        if fmt == "短文投稿" and len(posts) > 1:
            print(f"[SKIP] {title}: 短文投稿なのに区切り線があります", file=sys.stderr)
            failed += 1
            continue

        if dry_run:
            for i, text in enumerate(posts, 1):
                print(f"[DRY] {title} ({i}/{len(posts)}, 重さ{x_weight(text)}/{X_MAX_WEIGHT})\n{text}\n")
            posted += 1
            continue

        first_id = reply_to = None
        try:
            for text in posts:
                res = x_client.create_tweet(text=text, in_reply_to_tweet_id=reply_to)
                reply_to = res.data["id"]
                first_id = first_id or reply_to
                time.sleep(SLEEP_BETWEEN_POSTS_SEC)
        except Exception as e:
            print(f"[FAIL] {title}: Xへの投稿に失敗: {e}", file=sys.stderr)
            failed += 1
            if first_id is None:
                continue  # 何も出ていないので「確認中」のまま。次回やり直す

        # 1本でも出たら、二重投稿を防ぐために必ず「投稿済み」にする
        link = f"https://x.com/i/web/status/{first_id}"
        try:
            notion.mark_posted(page["id"], link)
        except Exception as e:
            print(
                f"[ERROR] {title}: 投稿は出ましたがNotionを更新できません。"
                f"手で「投稿済み」にしてください: {link} ({e})",
                file=sys.stderr,
            )
            return 1
        print(f"[OK] {title}: {link}")
        posted += 1

    print(f"[DONE] posted={posted}, skipped={skipped}, failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
