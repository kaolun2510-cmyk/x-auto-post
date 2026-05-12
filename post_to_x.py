"""X (Twitter) 予約投稿スクリプト

posts.csv を読み、status=pending かつ schedule_time が現在(JST)以前の行を
X API v2 で順次投稿する。投稿成功は status=posted、失敗は status=failed に
書き換えて CSV を上書き保存する。
"""

import csv
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import tweepy

CSV_PATH = "posts.csv"
JST = ZoneInfo("Asia/Tokyo")
SLEEP_BETWEEN_POSTS_SEC = 2
TIME_FORMAT = "%Y-%m-%d %H:%M"


def build_client() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_TOKEN_SECRET"],
    )


def parse_schedule(raw: str) -> datetime:
    return datetime.strptime(raw.strip(), TIME_FORMAT).replace(tzinfo=JST)


def main() -> int:
    if not os.path.exists(CSV_PATH):
        print(f"[ERROR] {CSV_PATH} not found", file=sys.stderr)
        return 1

    with open(CSV_PATH, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    required = {"schedule_time", "text", "status", "posted_at"}
    if not required.issubset(fieldnames):
        print(f"[ERROR] CSV must have columns: {sorted(required)}", file=sys.stderr)
        return 1

    now = datetime.now(JST)
    client = build_client()

    posted = 0
    failed = 0
    for row in rows:
        if row["status"] != "pending":
            continue
        try:
            scheduled_at = parse_schedule(row["schedule_time"])
        except ValueError as e:
            print(f"[SKIP] bad schedule_time '{row['schedule_time']}': {e}")
            row["status"] = "failed"
            row["posted_at"] = f"bad_time: {e}"
            failed += 1
            continue

        if scheduled_at > now:
            continue

        text = row["text"]
        try:
            client.create_tweet(text=text)
            row["status"] = "posted"
            row["posted_at"] = now.strftime(TIME_FORMAT)
            posted += 1
            print(f"[OK] posted: {text[:40]!r}")
            time.sleep(SLEEP_BETWEEN_POSTS_SEC)
        except Exception as e:
            row["status"] = "failed"
            row["posted_at"] = f"error: {e}"
            failed += 1
            print(f"[FAIL] {text[:40]!r}: {e}", file=sys.stderr)

    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[DONE] posted={posted}, failed={failed}, now={now.isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
