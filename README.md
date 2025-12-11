# get_tel_from_hp

企業 HP の URL 一覧を収めた CSV から、各サイトをクローリングして電話番号を抽出し、`url`,`tel` の CSV を出力するシンプルなスクリプトです。同一ドメイン内のリンクだけを幅優先で巡回し、本文テキストから正規表現で電話番号を検出します。

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 使い方

1. 少なくとも `url` 列を持つ CSV を用意します。

   ```csv
   url
   https://example.com
   https://example.org/company
   ```

2. スクリプトを実行し、出力 CSV を指定します。

   ```bash
   python get_tel_from_hp.py input.csv output.csv \
     --max-pages 100 \
     --delay 0.5
   ```

   - `--max-pages`: ドメインごとに巡回する最大ページ数 (既定値 100)
   - `--delay`: リクエスト間の待機秒数 (既定値 0)

3. 結果 CSV (`url`,`tel`) が生成されます。電話番号が見つからなかった場合は空欄になります。

## 実装メモ

- `requests` + `BeautifulSoup` で HTML を取得・解析しています。
- リンク巡回中に電話番号が見つかった時点で該当ドメインの探索を終了し、無駄なアクセスを抑えています。
- 電話番号は国内向けの代表的な書式 (`03-1234-5678`, `0120-123-456`, `+81-3-1234-5678` など) を想定した正規表現で抽出しています。
- Robots.txt などのサイトポリシーは考慮していないため、実運用前に各サイトの規約を確認してください。
