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

## 本社専用の抽出

`hq_tel_scraper.py` は本社以外の電話番号を極力取り除くための別スクリプトです。`hq_keywords.json` に定義した大量のキーワードを読み込み、「本社」「head office」「global headquarters」など本社を示す語が電話番号の近くに現れた場合のみ採用します。

```bash
python hq_tel_scraper.py input.csv hq_output.csv \
  --keywords hq_keywords.json \
  --max-pages 150
```

- ① 本社キーワードが半径 80 文字または DOM 上で 3 階層以内にある場合に本社番号としてマークします。
- ② 内部リンクを巡回した結果、10 桁以上の電話番号が 1 種類しか検出されなければ、その番号を本社として出力します。
- キーワードは JSON で管理しているため、追加・修正するだけで判定精度を調整できます (`primary_terms` が本社語、`support_terms` が関連語)。

## 実装メモ

- `requests` + `BeautifulSoup` で HTML を取得・解析しています。
- リンク巡回中に電話番号が見つかった時点で該当ドメインの探索を終了し、無駄なアクセスを抑えています。
- 電話番号は国内向けの代表的な書式 (`03-1234-5678`, `0120-123-456`, `+81-3-1234-5678` など) を想定した正規表現で抽出しています。
- Robots.txt などのサイトポリシーは考慮していないため、実運用前に各サイトの規約を確認してください。
