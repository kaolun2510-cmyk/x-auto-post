# X 自動予約投稿

## Notion の下書きから投稿する(`post_from_notion.py`)

Notion の「発信の下書き」で状態を **「確認中」** にした下書きを、GitHub Actions が30分ごとに拾って X に投稿します。投稿できたら状態を「投稿済み」にし、「投稿のリンク」に投稿先を残します。

- 対象は形式が「短文投稿」「連続投稿」のものだけ(「記事」「短い動画の台本」は投稿しません)
- 本文末尾の `(128字)` のような字数メモは投稿されません
- 連続投稿は、本文を **区切り線(`---`)** で1本ずつに分けてください
- 字数を超えた下書きは投稿せず「確認中」のまま残し、実行結果に理由を出します
  (X は改行も字数に数えるため、段落が複数あるときは全角140字ちょうどだと超えます)

### 準備

1. <https://www.notion.so/profile/integrations> で内部インテグレーションを作り、トークンを控える
2. Notion の「発信の下書き」を開き、右上の「…」→「接続」でそのインテグレーションを追加する
3. GitHub の **Settings → Secrets and variables → Actions** に登録する
   - `NOTION_TOKEN`(上のトークン)
   - `X_API_KEY` / `X_API_SECRET` / `X_ACCESS_TOKEN` / `X_ACCESS_TOKEN_SECRET`(下の手順1で取得)
4. **Actions** タブ →「Notion to X」→ **Run workflow** で「試し実行」にチェックを入れて動かすと、投稿せずに文面だけ確認できます

定期実行は、ワークフローが既定のブランチ(main)に入ってから動き始めます。

---

以下は、CSV から予約投稿する従来の仕組み(`post_to_x.py`)の説明です。

CSV に書いた投稿を、指定時刻に GitHub Actions が自動で X (Twitter) に流すツールです。

## 仕組み

- `posts.csv` に「投稿時刻・本文」を書く
- GitHub Actions が **15分ごと** に巡回し、時刻になったものから投稿
- 投稿済みの行は `status` が `posted` に書き換わって自動コミットされる

無料プランで月500投稿まで対応。Mac が起動していなくても、クラウド上で勝手に動きます。

---

## セットアップ手順

### 1. X 開発者アカウントを取得（初回のみ・無料）

1. <https://developer.x.com> に X アカウントでログイン
2. 「Sign up for Free Account」から開発者登録（自動承認・即日完了）
3. ダッシュボードで App を1つ作成
4. App の **User authentication settings** を開き、
   - App permissions: **Read and write**
   - Type of App: **Web App, Automated App or Bot**
   - Callback URL は適当でOK（例：`https://example.com`）
5. **Keys and tokens** タブから以下4つを発行・コピー：

   | 名前 | 用途 |
   |---|---|
   | API Key | Consumer Key |
   | API Secret | Consumer Secret |
   | Access Token | 投稿実行用 |
   | Access Token Secret | 投稿実行用 |

   ※ Access Token を発行する前に必ず権限を **Read and write** に変更しておくこと。読み取り権限のまま発行したトークンでは投稿できません。

### 2. GitHub リポジトリを作成

1. GitHub で新しいリポジトリを作成（Private 推奨）
2. このフォルダ（`x-auto-post/`）の中身をリポジトリのルートに置いて push

   ※ もし `x-auto-post/` ごとリポジトリに入れる場合は、ワークフローファイル（`.github/workflows/auto-post.yml`）をリポジトリ直下の `.github/workflows/` に移動してください。GitHub Actions はリポジトリ直下の `.github/workflows/` 以下しか認識しません。

### 3. GitHub Secrets に API キーを登録

リポジトリの **Settings → Secrets and variables → Actions → New repository secret** から、上で取得した4つのキーを以下の名前で登録：

- `X_API_KEY`
- `X_API_SECRET`
- `X_ACCESS_TOKEN`
- `X_ACCESS_TOKEN_SECRET`

**絶対にコードや CSV に書かないでください。** `.env` ファイルも `.gitignore` で除外済みですが、念のため自分で作る場合も注意。

### 4. 投稿予定を `posts.csv` に書く

```csv
schedule_time,text,status,posted_at
2026-05-13 09:00,おはようございます！,pending,
2026-05-13 12:30,お昼の投稿。,pending,
```

- `schedule_time`: 日本時間で `YYYY-MM-DD HH:MM` 形式
- `text`: 投稿本文（280文字まで、改行を含めるなら `"..."` でくくる）
- `status`: 新規行は必ず `pending`
- `posted_at`: 空欄でOK（自動で埋まる）

編集したら push。

### 5. 動作確認

1. **手動トリガー**: リポジトリの **Actions** タブ → 「X Auto Post」→ **Run workflow** で即時実行
2. 過去日時の行を1つ仕込んで実行 → 実際に投稿されればOK
3. ログで `[OK] posted: ...` を確認、`posts.csv` に自動コミットが入ることを確認

以降は15分ごとに自動巡回します。

---

## ローカルでテストする場合

```bash
cd x-auto-post
pip install -r requirements.txt

export X_API_KEY=xxxxx
export X_API_SECRET=xxxxx
export X_ACCESS_TOKEN=xxxxx
export X_ACCESS_TOKEN_SECRET=xxxxx

python post_to_x.py
```

時刻が来ていない行はスキップされます。テストしたい場合は `posts.csv` に過去日時の行を入れてください。

---

## トラブルシューティング

| 症状 | 原因 |
|---|---|
| `403 Forbidden` で投稿失敗 | App 権限が Read only のまま、または Access Token を権限変更前に発行している。Read and write にした後、Access Token を再発行する |
| `429 Too Many Requests` | 月500投稿の無料上限到達。翌月まで待つか有料プランへ |
| 自動コミットが走らない | リポジトリ Settings → Actions → General → **Workflow permissions** を「Read and write」に設定 |
| 時刻ぴったりに投稿されない | cron は15分間隔のため最大15分の遅延が出ます。短くしたい場合は `auto-post.yml` の cron を `*/5 * * * *` 等に変更 |

---

## 注意事項

- 自動投稿は X の利用規約（[Automation rules](https://help.x.com/en/rules-and-policies/x-automation)）の範囲内で行ってください。スパム的な大量投稿は禁止です。
- 無料プランの上限：**月500投稿**
- API キーが漏えいすると第三者にアカウントを乗っ取られます。**絶対にコミットしない**こと。
