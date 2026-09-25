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

**Python版CLIを標準の実行入口**として案内します。現時点では実験的な入口であり、従来のBash版も利用できます。

- **macOS（Apple Silicon）**: Python 3.10.4で使い捨ての公開候補から仮想環境・フォントを新規構築し、合成画像１ページのOCR、検索可能PDF、Ghostscript圧縮後の文字保持を検証しました。
- **Windows x64（物理Boot Camp環境）**: Python 3.13.15 AMD64でPython版セットアップと合成画像・PDF・画像フォルダの検索可能PDF生成、日本語・空白を含む入力パスを検証しました。
- **未検証**: Linuxでのend-to-end実行、Windows ARM64、ARM上のWindows x64エミュレーション、Windowsでの実際のGhostscript圧縮、Windowsでの実資料OCR精度。すべてのPython/OSの組合せでの動作を保証するものではありません。

Python 3.10–3.13、`requirements-paddle.txt` のPaddleOCR / PaddleX / ONNX Runtime、および `requirements-helper.txt` のPDF・画像処理ライブラリを使います。Ghostscriptは圧縮版PDFを作る場合のみ必要です。

## セットアップと実行（Python版・標準入口）

リポジトリをcloneしてから、インストール済みの対応Pythonを明示して実行します。Python環境の作成とフォント取得は**別々の明示的なコマンド**です。既存の正常な環境・フォントは原則再利用し、使用できない既存仮想環境をセットアップスクリプトが無断で置き換えることはありません。初回のOCR実行時にはモデルの取得が必要になる場合があります。

### macOS

```bash
cd "/path/to/paddleocr-searchable-pdf-pipeline"
python3 tools/setup_python_envs.py --check
python3 tools/setup_python_envs.py --install-envs
python3 tools/setup_fonts.py --install-fonts
.venv/bin/python paddleocr_cli.py "/path/to/input.pdf" --check
.venv/bin/python paddleocr_cli.py "/path/to/input.pdf" my_new_job 180
```

`python3` がPython 3.10–3.13を指すことを確認してください。上の `--check` はジョブを作らず入力・実行環境・フォントを検査します。最後の `180` は描画DPIで、ジョブ名・DPIを省略することもできます。

### Windows x64（PowerShell）

Python 3.10–3.13の**x64版**を事前に導入してください。次は検証に用いたPython 3.13の呼び出し例です。別バージョンを使う場合は `py -V:3.13` をその版に合わせて変更します。

```powershell
Set-Location "C:\path\to\paddleocr-searchable-pdf-pipeline"
py -V:3.13 tools/setup_python_envs.py --check
py -V:3.13 tools/setup_python_envs.py --install-envs
py -V:3.13 tools/setup_fonts.py --install-fonts
& ".\.venv\Scripts\python.exe" ".\paddleocr_cli.py" "C:\path\to\input.pdf" --check
& ".\.venv\Scripts\python.exe" ".\paddleocr_cli.py" "C:\path\to\input.pdf" "my_new_job" 180
```

検証したWindows x64実機では、ONNX RuntimeのDLL読み込みのためにMicrosoft Visual C++ Redistributable x64が必要でした。Python版CLIは子プロセスの日本語ログをUTF-8で処理するため、PowerShellで文字コード用の環境変数を手動設定する必要はありません。

**Windows ARM64（未検証）:** Windows ARM64上では、ARM64ネイティブ版Pythonではなく、Windows用x64版Python 3.10–3.13と本リポジトリの既存依存関係を利用する構成を検討対象としています。ただし、Windows ARM64上でのx64エミュレーションによる本パイプラインの動作は未検証であり、現時点では対応環境として案内していません。ARM64ネイティブ版Pythonを用いるセットアップは現在の対象外です。

**入力**にはPDF・単一画像・ページ画像のディレクトリを指定できます。入力ファイル・処理設定を変更するときは新しいジョブ名を使ってください。既存ジョブの中間成果物を誤って再利用しないため、Python版は入力識別記録が一致しないジョブの再利用を拒否します。

### ２回目以降の実行（初回セットアップ済みの場合）

仮想環境と日本語フォントのセットアップは、通常、OCRのたびに繰り返す必要はありません。新しい入力を処理する場合は、次の実行コマンドだけで開始できます。

macOS（ターミナル）:

```bash
cd "/path/to/paddleocr-searchable-pdf-pipeline"
.venv/bin/python paddleocr_cli.py "/path/to/input.pdf"
```

PDFのパスは、Finderからターミナルへのドラッグ＆ドロップや「パス名をコピー」で入力できます。リポジトリ直下の `.venv` がない既存の開発環境では、必要な依存関係を備えていれば `.venv_paddle/bin/python` をCLIの起動に使うこともできます。その場合も、CLIはOCR用・PDF処理用のPythonを別途選択します。

Windows x64（PowerShell）:

```powershell
Set-Location "C:\path\to\paddleocr-searchable-pdf-pipeline"
.\.venv\Scripts\python.exe .\paddleocr_cli.py "C:\path\to\input.pdf"
```

入力PDFのパスはエクスプローラーの「パスのコピー」で取得して貼り付けられます。環境によってはエクスプローラーからターミナルへのドラッグ＆ドロップでも指定できます。上の実行例ではPython実行ファイルのパスに空白がないため、PowerShellの `&` と引用符を省略できます。別の場所のPythonなど、空白を含む実行ファイルのパスを使う場合は `& "C:\path with spaces\python.exe" ...` の形式にしてください。

job名を省略すると、新しい日時付きjob名が生成されます。同じjobを再開する場合は元の入力・設定・job名を一致させ、**入力や処理設定を変更する場合は新しいjob名を使用**してください。詳細なjob名・DPIの指定は上のセットアップ節の実行例を参照してください。

### 従来のBash版（macOSの既存利用者向け）

従来の入口 `paddleocr.sh` とセットアップ `tools/setup.sh` は残しています。既存のBash版ワークフローを継続する場合に利用してください。Bash版のセットアップは回帰テスト等もまとめて実行するため、Python版の２つのセットアップコマンドと完全に同じ処理ではありません。

```bash
bash tools/setup.sh
./paddleocr.sh "/path/to/input.pdf"
```

WindowsでPython版を利用するためにBashを導入する必要はありません。

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
python3 tools/setup_fonts.py --install-fonts
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
.venv/bin/python paddleocr_cli.py "/path/to/input.pdf"
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

標準入口は `paddleocr_cli.py` です。macOSでの例:

```bash
.venv/bin/python paddleocr_cli.py "/path/to/input.pdf"
.venv/bin/python paddleocr_cli.py "/path/to/input.pdf" my_new_job 180
```

Windowsでは `& ".\.venv\Scripts\python.exe" ".\paddleocr_cli.py" "C:\path\to\input.pdf" "my_new_job" 180` の形式で実行します。初回の実行前には `--check` で入力と環境を確認できます。

入力にはPDF、単一画像、ページ画像を入れたディレクトリを指定できます。入力文書・処理設定を変える際は新しいジョブ名を使ってください。既存ジョブには再開用の中間成果物が残ります。

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

既存のcompact JSONは既定で再利用します。同一の入力・設定でOCRを強制的にやり直す場合、macOSでは次のように実行します。

```bash
PADDLE_OVERWRITE=1 .venv/bin/python paddleocr_cli.py "/path/to/input.pdf" same_job_name 180
```

Windows PowerShellでは、実行前に `$env:PADDLE_OVERWRITE = "1"` を指定してください。再実行時は元の入力・設定とジョブ名の整合性を確認し、別の入力には新しいジョブ名を使ってください。

## 大きすぎるPDFページ

指定DPIで推定25 million pixelsを超えるPDFページは、既定で長辺およそ3400pxになるようOCR前に正規化します。通常サイズのページは変更しません。

macOSで正規化を無効にする場合:

```bash
PADDLE_NORMALIZE_PDF=0 .venv/bin/python paddleocr_cli.py "/path/to/input.pdf"
```

閾値を調整する場合:

```bash
PADDLE_MAX_PIXELS=30000000 PADDLE_TARGET_LONG_EDGE_PX=3800 \
  .venv/bin/python paddleocr_cli.py "/path/to/input.pdf" my_new_job 180
```

Windows PowerShellでは対応する環境変数を `$env:PADDLE_NORMALIZE_PDF = "0"` などの形式で設定します。処理設定を変更する場合、既存ジョブの再利用は行わず新しいジョブ名を使ってください。

## 検証とsmoke test

検索可能PDFの生成後、実際に文字を抽出して検証します。Ghostscriptが利用できる場合は150dpi向けの圧縮版PDFも生成し、圧縮前後の文字保持を確認します。Ghostscriptがなくても通常版の検索可能PDFは作成できます。

公開版に含まれるPython回帰テストは、**セットアップ後**にmacOSで次のように実行できます。

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
```

従来のBash版向け `bash tools/smoke_test_public.sh` はmacOS上で公開ツリーの静的検査に利用できます。入力ファイルを渡すend-to-endモードは引き続き**Bash版を起動します**。WindowsのPython版CLI実行テストの入口ではありません。

## サードパーティソフトウェア

このrepositoryには、PaddleOCR、PaddleX、日本語フォント本体、PyMuPDF/MuPDF、Ghostscriptのソースツリーは含めません。それぞれのライセンスについては `THIRD_PARTY_LICENSES.md` を参照してください。