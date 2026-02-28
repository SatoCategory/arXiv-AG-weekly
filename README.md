# arxiv-ag-weekly

毎週木曜 9:00 (JST) に arXiv **math.AG** の新着から先生の関心に近い論文を自動抽出し、
**主定理（自動抽出）**・タイトル・著者・URL を **PDF** にまとめるワークフローです。

- 取得: arXiv **公式API (Atom)** を使用（礼儀として User-Agent に連絡先を付与）。
- 連続アクセスの間隔: **3秒**（arXiv APIの推奨に従う）。
- 出力: 上位3件は詳細（主定理/URL付き）、4件目以降は**タイトルのみ**。0件なら"0件でした"とPDF出力。
- スケジュール: **GitHub Actions** の `schedule` (UTC) を用いて木曜 0:00 UTC（= JST 9:00）に起動。

> arXiv APIの構造やレート、RSS/ATOM の仕様、GitHub Actions の cron が **UTC 解釈**である点は公式情報をご確認ください。

## 使い方

### 1) 依存関係

```bash
pip install -r requirements.txt
```

### 2) 設定 (`config.yaml`)
- キーワードや優先著者を編集して、スコアリングを調整できます。
- 直近対象日数 (`lookback_days`) や抽出しきい値 (`threshold`) も調整可能。

### 3) ローカル実行

```bash
export ARXIV_CONTACT="your_email@example.com"  # arXivへの礼儀として連絡先をUAに
python main.py
# 生成物: out/weekly_math_ag_YYYY-MM-DD.pdf
```

### 4) GitHub Actions で毎週実行

1. このリポジトリを GitHub にプッシュ
2. **Actions** を有効化
3. `.github/workflows/weekly.yml` のスケジュールで毎週 木曜 0:00 UTC に自動実行
   - JST の木曜 9:00 に相当します
4. 実行後、Artifacts に PDF が保存されます

（ヒント）実行時間のばらつきを避けたい場合は、`cron` の分を `0` 以外にする等も有効です。

## 注意・ポリシー
- arXivの**メタデータ**（タイトル・要旨等）は CC0 ですが、**PDFの再配布は不可**です。本ワークフローは URL を記載するのみで再配布は行いません。
- arXiv API には**レート制限**と**利用指針**があります。連続呼び出しは 3 秒以上の間隔を空け、結果はキャッシュするなど、混雑を避ける実装にしています。

## ライセンス
MIT
