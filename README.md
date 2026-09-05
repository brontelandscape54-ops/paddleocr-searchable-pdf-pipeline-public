# PaddleOCR Searchable PDF Pipeline

日本語 | [English](README_en.md)

PaddleOCRを利用して、PDF・単一画像・画像フォルダから**検索可能PDF**と構造化OCR成果物を作るための実用パイプラインです。日本語の古典籍・近世近代史料・寺社文書など、旧字・異体字や複雑な版面を含む資料での利用を意識しています。

> This is an unofficial independent project using PaddleOCR. It is not affiliated with or endorsed by PaddlePaddle.

## このパイプラインの特徴

- **日本語史料・古典籍を意識したOCRワークフロー** — 旧字・異体字・CJK拡張文字を含む資料を想定しています。
- **原画像をそのまま保持した検索可能PDF** — 表示面はスキャン画像のままで、OCR結果を透明なUnicodeテキストレイヤーとして重ねます。
- **表・挿図・罫線・欄外書き込みなど複雑な版面を視覚的に保持** — OCR文字列からページを描き直さないため、原資料の見た目を崩しません。
- **文字単位のフォントフォールバック** — M PLUS 1p と Jigmo / Jigmo2 / Jigmo3 を組み合わせ、広いCJK文字範囲を扱います。
- **再現性と検証を重視** — OCR依存関係の固定、フォント取得時の整合性確認、PDF/CMap回帰テスト、検索テキスト保持確認を行います。

## なぜPaddleOCR中心の構成なのか

開発過程ではMarkerも詳しく検証し、OCRに成功した箇所の品質は非常に良好でした。Markerの `blocks.json` から文字列とbboxを取り出し、原画像保持型searchable PDFを作るところまでも成立しています。そのため、Markerを採用しなかった理由は「認識精度が低かったから」ではありません。

一方、当時の開発環境ではMarker内部の文字認識が実用上重く、複数ページ処理ではMPSメモリ不足も発生しました。OCRを無効にしたMarkerのTableCell検出は高速だったため、一時は「Markerで表構造、PaddleOCRで文字認識」というハイブリッドも検討しました。

その後、同じ表資料で複数OCRを比較し、総文字数や全文類似度だけでなく、原画像付き168セル比較やMarker TableCellへのPaddleOCR bbox割り当てまで行いました。その結果、PaddleOCR単独でも実用的な文字認識とbboxを得られることを確認しました。最終目的は表をExcel等へ完全に論理復元することではなく、**原ページ画像を保持したまま検索可能にすること**だったため、本番構成はより単純なPaddleOCR中心のパイプラインへ収束しました。

比較経緯、実測値、評価方法の限界は [開発背景と設計判断](docs/DEVELOPMENT_BACKGROUND.md) に詳しくまとめています。

## 図表・複雑な版面に向いている理由

検索可能PDFでは、**元のスキャン画像そのものを表示面として保持**し、その上にOCR結果を透明なUnicodeテキストとして配置します。

そのため、次のような要素をOCR結果から無理に再構成する必要がありません。

- 表組み・罫線
- 挿図・図版
- 印章
- 欄外書き込み
- 変則的な文字配置
- 古典籍や史料特有の複雑な版面

見た目は原画像のままなので、プレーンテキスト化だけでは失われるページ上の情報を保ちつつ、全文検索や文字コピーを可能にできます。

**注意:** これは表の論理構造をExcelのように復元する専用のtable extractionエンジンではありません。行・列・セル構造を完全に再構築することを目的としたものではなく、**図表を含む原ページの見た目を保ったまま検索可能化すること**が強みです。

## 処理の流れ

```text
PDF / 画像 / 画像フォルダ
→ 巨大PDFページのOCR-safe前処理
→ ページ画像化
→ PaddleOCR
→ ページごとの JSON / TXT
→ TXT / Markdown / JSON / JSONL 結合
→ 日本語フォントの文字単位フォールバック
→ ページごとの検索可能PDF
→ PDF結合
→ 検索テキスト検証
→ 任意でGhostscriptによる圧縮版PDF生成
```

検索可能PDF生成では、実在するTrueTypeフォントを埋め込み、各フォントのcmapを確認して文字ごとに使用フォントを選択します。

## 動作確認環境

現在、主として **macOS** で検証しています。

- Bash
- Python 3.10–3.13
- `requirements-paddle.txt` に固定した PaddleOCR / PaddleX / ONNX Runtime
- `requirements-helper.txt` のPDF・画像処理ライブラリ
- 圧縮PDF生成用のGhostscript（`gs`、任意）

主要処理から既知のmacOS固有依存はできるだけ除いており、一般的なLinuxフォントパスにも対応しています。ただしLinuxでの完全なend-to-end検証はまだ行っていないため、現時点では正式な検証済み対象とはしていません。

## セットアップ

clone後、次を実行します。

```bash
bash tools/setup.sh
```

このコマンドで次を行います。

1. Python 3.10–3.13 の確認
2. PaddleOCR / PaddleX / ONNX Runtime用 `.venv_paddle` の作成または再利用
3. PDF処理等に使う `.venv` の作成または再利用
4. 推奨日本語フォントをGit管理外の `fonts/` に取得
5. フォント配布元・チェックサムの検証
6. PDF/CMap回帰テスト
7. Jigmoの補助面文字を使った実PDF生成・抽出検証
8. public tree のstatic smoke test

既存の正常な仮想環境は再利用します。利用者が自分で配置したフォントも、原則として上書きしません。

主なオプション:

```bash
bash tools/setup.sh --rebuild       # 2つのPython環境を作り直す
bash tools/setup.sh --no-fonts      # 推奨フォントを取得しない
bash tools/setup.sh --force-fonts   # setup管理下のフォントを置換する
```

repositoryをcloneしただけでは外部ダウンロードは実行されません。フォント取得は `tools/setup.sh` または `tools/setup_fonts.sh` を明示的に実行したときだけ行われます。

通常の実行入口は次です。

```bash
./paddleocr.sh "/path/to/input.pdf"
```

### 手動セットアップ

個別に構築したい場合は、次のようにも実行できます。

```bash
bash tools/rebuild_paddle_venv.sh

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-helper.txt

bash tools/setup_fonts.sh
bash tools/smoke_test_public.sh
```

## 日本語フォントフォールバック

フォントフォールバックは見た目だけの機能ではなく、検索可能PDFのUnicodeテキストレイヤーを成立させるための重要な処理です。

推奨順は次です。

```text
MPLUS1p-Medium.ttf
→ Jigmo.ttf
→ Jigmo2.ttf
→ Jigmo3.ttf
```

OCR文字ごとに各TTFのcmapを調べ、そのUnicodeコードポイントを含む最初のフォントを選択します。

- **M PLUS 1p** — 通常の日本語文字を主に担当
- **Jigmo** — M PLUSにないBMP / Extension A周辺の漢字を補完
- **Jigmo2 / Jigmo3** — Unicode 17.0 / Extension Jまでの補助面CJK文字を補完
- どのフォントにもない文字はunsupportedとして記録・警告

元文字がない場合には、一文字だけのNFKC正規化形も試します。ただし、これは適切な歴史的文字フォントの代替ではありません。

Jigmo移行時には実在する10ページの日本語史料OCRで旧Hanazono構成と比較し、両者とも `M PLUS 7870文字 + fallback 14文字 / 9種 / unsupported 0` で一致しました。また、補助面文字 `U+20000` をJigmo2でPDF化し、pypdfで完全一致抽出でき、GhostscriptでもCMap警告なく解析できることを確認しています。

### フォントの取得・指定

フォント本体はGit履歴には含めません。

推奨フォントは次で取得できます。

```bash
bash tools/setup_fonts.sh
```

ローカルには次のように配置されます。

```text
fonts/
├── MPLUS1p-Medium.ttf
├── Jigmo.ttf
├── Jigmo2.ttf
├── Jigmo3.ttf
└── licenses/
```

配布元・ライセンスについては `THIRD_PARTY_LICENSES.md` を参照してください。

自分でTTFを配置したり、`PADDLE_PDF_FONTS` で明示指定したりすることもできます。

```bash
export PADDLE_PDF_FONTS="$PWD/fonts/MPLUS1p-Medium.ttf:$PWD/fonts/Jigmo.ttf:$PWD/fonts/Jigmo2.ttf:$PWD/fonts/Jigmo3.ttf"
./paddleocr.sh "/path/to/input.pdf"
```

macOS / Linux の一般的なシステムフォント場所も探索します。

```text
~/Library/Fonts
/Library/Fonts
/System/Library/Fonts/Supplemental
~/.local/share/fonts
~/.fonts
/usr/local/share/fonts
/usr/share/fonts
```

`paddle_json_to_searchable_pdf.py` や `tools/report_font_fallbacks.py` を直接使う場合、`--font-path` は優先順に複数回指定できます。1つでも明示指定した場合は、そのフォントだけを使い、自動検出フォントを後から追加しません。`PADDLE_PDF_FONTS` も同じく明示的な優先順として扱います。

利用可能な日本語TTFが見つからない場合は、未知の代替フォントで黙ってPDFを作るのではなくエラーで停止します。

### どのフォントが使われたか確認する

PDF生成時には、登録した各フォントと使用文字数、unsupported文字数を表示します。

既存のPaddleOCR JSONから、OCRをやり直さずに詳細なフォント割当を調べるには次を使います。

```bash
.venv/bin/python tools/report_font_fallbacks.py \
  jobs/<job_name>/paddle_ocr/json
```

Jigmo補助面のPDF経路を単独検証する場合:

```bash
.venv/bin/python tools/validate_jigmo_supplementary.py
```

## 使い方

PDFをOCRする場合:

```bash
./paddleocr.sh "/path/to/input.pdf"
```

job名と描画DPIを指定する場合:

```bash
./paddleocr.sh "/path/to/input.pdf" my_job_name 180
```

入力にはPDF、単一画像、ページ画像を入れたディレクトリを指定できます。

入力文書が変わった場合は新しいjob名を使ってください。同じjob名では、再開機能により既存のページ画像やOCR JSONを意図的に再利用することがあります。

## 出力

```text
jobs/<job_name>/
├── preprocessed/
├── pages/
├── paddle_ocr/
│   ├── json/
│   ├── txt/
│   ├── font_fallback_report/
│   └── paddle_batch_summary.csv
├── output/
│   ├── <name>_paddle.txt
│   ├── <name>_paddle.md
│   ├── <name>_paddle.json
│   └── <name>_paddle_pages.jsonl
├── searchable_pdf/
│   ├── pages_pdf/
│   ├── <name>_paddleocr_searchable.pdf
│   └── <name>_paddleocr_searchable_small_150dpi.pdf
└── logs/
```

`jobs/` はGit管理外です。中間OCR結果やトラブルシュートに役立つ情報を含むため、単なる使い捨て一時ファイルとして扱う設計ではありません。

## OCRをやり直す

既存のcompact JSONは既定で再利用されます。OCRを強制的にやり直す場合:

```bash
PADDLE_OVERWRITE=1 ./paddleocr.sh "/path/to/input.pdf" same_job_name 180
```

## 大きすぎるPDFページ

指定DPIで推定25 million pixelsを超えるPDFページは、既定で長辺およそ3400pxになるようOCR前に正規化します。通常サイズのページは変更しません。

無効化する場合:

```bash
PADDLE_NORMALIZE_PDF=0 ./paddleocr.sh "/path/to/input.pdf"
```

閾値を調整する場合:

```bash
PADDLE_MAX_PIXELS=30000000 \
PADDLE_TARGET_LONG_EDGE_PX=3800 \
./paddleocr.sh "/path/to/input.pdf" my_job 180
```

## 検証とsmoke test

このパイプラインは「PDFが生成できた」だけでは成功扱いにしません。ページPDF結合後に、検索可能テキストを実際に抽出できることを検証します。

Ghostscriptがある場合は、150dpi向けの小容量PDFも生成し、圧縮前後で十分な検索テキストが保持されていることを確認します。保持確認に失敗した圧縮PDFは成功成果物として残しません。

static smoke test:

```bash
bash tools/smoke_test_public.sh
```

任意の入力を使ったend-to-end OCR smoke test:

```bash
bash tools/smoke_test_public.sh "/path/to/input.pdf"
```

回帰テストには、空OCRページとReportLab ToUnicode CMap互換修正、補助面Unicodeマッピングの検証が含まれます。

Ghostscriptは任意です。`gs` がなくても通常の検索可能PDFは生成でき、圧縮工程だけがスキップされます。

## サードパーティソフトウェア

このrepositoryには、PaddleOCR、PaddleX、日本語フォント本体、PyMuPDF/MuPDF、Ghostscriptのソースツリーは含めません。それぞれのライセンスについては `THIRD_PARTY_LICENSES.md` を参照してください。