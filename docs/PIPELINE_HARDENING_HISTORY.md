# PaddleOCRパイプライン実用化・堅牢化史

[日本語] | [English](PIPELINE_HARDENING_HISTORY_en.md)

この文書は、[OCR選定史補遺](OCR_SELECTION_HISTORY_SUPPLEMENT.md) の続編です。

前編では、Marker、NDL古典OCR-Lite、Yomitoku、PaddleOCR等を比較し、なぜ最終的にPaddleOCR中心の構成へ収束したかを扱いました。本書では、**PaddleOCRを主軸にすると決めた後、1ページの比較実験を、PDFを直接渡して繰り返し使える実用パイプラインへ発展させた過程**を記録します。

主な対象期間は2026年6月21日以降です。以下の時間・容量・文字数等は、当時の特定資料・Mac・設定による開発記録です。一般性能を示すベンチマークではありません。

## 1. 出発点: 1ページでは成功していたが、5ページ一括版はまだ壊れていた

PaddleOCRの1ページ比較版では、次の構成がすでに成功していました。

```text
PP-OCRv6_small_det
PP-OCRv6_small_rec
engine = onnxruntime
provider = CPUExecutionProvider
```

代表的な表ページでは、214 OCR領域、726文字、平均confidence 0.9741を得て、PaddleOCR JSONから原画像保持型searchable PDFを生成し、PDFから720文字を抽出できていました。

しかし、最初の5ページ一括版は別の初期化条件を持っていました。

```text
PP-OCRv5_mobile_det
PP-OCRv5_mobile_rec
engine = paddle
```

当時の `.venv_paddle` には `paddlepaddle` を入れておらず、ONNX Runtimeを使う環境だったため、一括版は次のエラーで停止しました。

```text
Engine 'paddle_static' is unavailable because dependency 'paddlepaddle' is not installed.
```

ここで行った修正は、新しいエンジンを追加することではなく、**すでに成功していた1ページ版の条件を一括版へ正確に移すこと**でした。

その結果、5ページ一括版も `PP-OCRv6 small + ONNX Runtime + CPUExecutionProvider` へ統一されました。

## 2. 5ページで「最小実用品」が成立

修正後、5ページの資料について次を一度に完走しました。

```text
ページ画像
→ 全ページPaddleOCR
→ ページ別JSON / TXT
→ ページ別searchable PDF
→ 5ページ結合searchable PDF
→ PDFテキスト抽出検証
```

OCRログの一例は次のとおりです。

```text
page 1: 0.82 s / 2 lines / 14 chars
page 2: 6.20 s / 214 lines / 726 chars
page 3: 7.18 s / 273 lines / 845 chars
page 4: 6.73 s / 248 lines / 825 chars
page 5: 5.81 s / 206 lines / 773 chars
```

結合PDFではページ別に14、720、845、824、773文字を抽出し、合計**3176文字**を確認しました。

この時点で、PaddleOCR単独で

```text
OCR
→ 構造化中間成果物
→ searchable PDF
→ 結合
→ 検証
```

まで成立する「実用最小形」に到達しました。

## 3. 「止まって見える」ことも実用品では障害だった

5ページ成功時、OCRそのものより先に別の問題が見えました。

モデルファイルはすでにcacheされているのに、

```text
Creating model: ...
Model files already exist. Using cached files.
```

の後で長時間表示が更新されず、処理が止まったのか、初期化中なのか利用者から分からない状態でした。

PaddleOCR / ONNX Runtimeは実行ごとにモデル読み込みと推論session初期化を行うため、モデルdownloadが終わっていても初期化時間は発生します。また当時の計測は、モデル初期化後から開始しており、表示された総時間に初期化時間が入っていませんでした。

そこで、進捗率を推測して見せるのではなく、次を追加しました。

- モデル初期化開始を明示
- 初期化中は10秒ごとに経過時間を表示
- 初期化完了時間を表示
- `flush=True` とunbuffered出力で表示遅延を減らす
- 全体所要時間へ初期化時間も含める
- 既存JSONだけで再実行できる場合はモデルを初期化しない

典型的な表示は次の形です。

```text
[INIT] PaddleOCRモデルとONNX Runtimeを初期化しています...
[INIT] 初期化中... 10秒経過
[INIT] 初期化中... 20秒経過
[OK] PaddleOCR初期化完了: ...秒
```

ここで導入した**遅延初期化**は、後の再実行性に重要でした。すべてのページJSONが存在する場合、OCRモデルを読み込まず、PDF再生成や検証だけを行えるようになりました。

## 4. 固定テストから「PDFを渡すだけ」の汎用入口へ

次の課題は、固定された5枚のページ画像を処理するテストから、実際のPDFを利用者が直接渡せる形へ移すことでした。

既に運用していた別のNDL系OCRコードセットの設計から、次の考え方を参考にしました。

- 巨大PDFページだけをOCR-safeに正規化する
- PDFをページ画像へ展開する
- 工程ごとにログを分ける
- 途中成果物を残して再実行可能にする
- ページ別結果と統合結果を分離する
- PDF生成後に検索テキストを実際に検証する

PaddleOCR版では、これを次の流れへまとめました。

```text
PDF / image / image directory
→ oversized-page normalization
→ page images
→ PaddleOCR
→ per-page JSON / TXT
→ merged TXT / Markdown / JSON / JSONL
→ per-page searchable PDFs
→ merged searchable PDF
→ text-layer verification
→ optional Ghostscript compression
```

中間成果物は `jobs/<job_name>/` 以下へ保存し、再実行時に使える設計としました。

この段階で内部本体 `paddleocr_input.sh` が成立しました。

## 5. helper Pythonの「存在確認」では不十分だった

最初のPDF直接入力試験は、OCRを始める前に停止しました。

プロジェクト内に `.venv/bin/python` は存在していましたが、そのPythonにはPDF前後処理で必要なPyMuPDFの `fitz` が入っていませんでした。

つまり、

```text
Python executable exists
```

だけでは、

```text
this Python can run the helper pipeline
```

を意味しません。

この失敗から、利用者向け入口を `paddleocr.sh` とし、候補Pythonごとに必要モジュールを**実際にimportしてから採用する**方式へ変更しました。

後に確認対象は、概ね次へ拡張されました。

```text
fitz / PyMuPDF
Pillow
ReportLab
pypdf
fontTools
```

役割分担は現在も次の形です。

```text
paddleocr.sh
  → 利用者向けランチャー
  → 実行可能なPaddleOCR/helper Pythonを選ぶ

paddleocr_input.sh
  → 前処理・OCR・統合・PDF生成・検証・圧縮を管理する内部本体
```

この分離は、単なるファイル名整理ではなく、実際の依存選択失敗から生まれました。

## 6. 圧縮版PDFができても、検索可能とは限らなかった

通常版searchable PDFは成功していましたが、初期の150dpi圧縮版では検索テキストが失われる問題が発生しました。

当時の圧縮は、完成済みsearchable PDFをGhostscript `pdfwrite` で再構築し、画像をダウンサンプリングする方式でした。

最初のPaddleOCR PDFレンダラはReportLabのCIDフォント、

```text
HeiseiKakuGo-W5
```

を使っていました。Ghostscript処理ではこれが別のfallback fontへ置換され、圧縮後PDFから検索文字列を正常に抽出できなくなりました。

重要なのは、ここで「Ghostscriptが終了コード0なら成功」としなかったことです。

検索可能PDFにとっての成功条件を、

```text
PDFファイルが生成された
```

から、

```text
生成後のPDFから検索文字列を抽出できる
```

へ引き上げる必要が明確になりました。

## 7. NDL系の実績から実在TTFへ移行

既存のNDL系OCRコードセットを調べると、searchable PDFでは実在する

```text
MPLUS1p-Medium.ttf
```

をReportLabの `TTFont` として登録していました。

そこでPaddleOCR版もCID fontをやめ、実在TTFを埋め込む方式へ変更しました。透明文字の描画も、NDL系で実績のあった方式へ寄せました。

さらに圧縮後に抽出文字数を比較し、一定以上失われた圧縮版は成功成果物として残さない仕組みを追加しました。

この経験は、現在の「通常版を必ず残し、圧縮版は検証に通った場合だけ成功扱いする」という方針の起点です。

## 8. M PLUSだけでは旧字・異体字を覆えなかった

実資料を再確認すると、M PLUS 1pだけでは収録されていない文字がありました。

既存のNDL/Yomitoku系hybrid実装では、

```text
MPLUS1p-Medium.ttf
→ HanaMinA.ttf
→ HanaMinB.ttf
```

を文字単位で切り替える仕組みを既に持っていました。

PaddleOCR版にもこのcmapベースのフォント選択を移植しました。

5ページ実資料では、M PLUSにない**15種類・30文字**がHanaMinAへ割り当てられました。例として、`圖`、`據`、`癡`、`說`、`辨`、`錄`、`關`、`闡`、`隱`、`黑` 等が含まれました。

この試験では、

```text
HanaMinA: 使用あり
HanaMinB: 0
unsupported: 0
```

でした。

フォールバックを含む通常版・150dpi圧縮版の双方から**3194文字**を抽出し、保持率1.000を確認しました。

その後、どの文字がどのフォントへ回ったかをOCRし直さず監査できる `tools/report_font_fallbacks.py` も追加しました。

> 注: 現在のpublic版標準フォールバックはHanaMinではなく `M PLUS → Jigmo → Jigmo2 → Jigmo3` です。ここでは2026年6月当時の開発史としてHanaMin構成を記録しています。

## 9. 圧縮後検証は「文字数」から「内容」へ強化された

初期の圧縮後検証は、圧縮前後の抽出文字数を比較する方式でした。

しかし、文字数が同じでも一部文字が別字へ変化している可能性は残ります。また当時はGhostscriptからCMapに関する警告も出ていました。

そこで関連するNDL系コードセットでは、検証をさらに次へ強化しました。

```text
ページ数一致
→ ページ別抽出文字数
→ 正規化後のページ別文字列比較
→ 全文一致
```

実際の5ページ試験では、通常NDL版で2842→2842文字、古典OCR版で3626→3626文字となり、各ページ `similarity=1.000000`、`exact normalized text match: OK` を確認しました。

PaddleOCR開発で見つかった問題が、他のOCRコードセット側の安全検証も強化する結果になりました。

## 10. 実験場から独立パイプラインへ改名

開発開始時は、Marker、NDL、Yomitoku、PaddleOCRを比較する実験場で、repository名とローカル作業ディレクトリ名も比較実験を反映したものでした。

しかし6月21日の時点で、実態は

```text
PDF入力
→ 前処理
→ PaddleOCR
→ 構造化成果物
→ searchable PDF
→ 圧縮
→ 圧縮後検証
```

までを行う独立したPaddleOCRパイプラインになっていました。

そこで正式名称を

```text
paddleocr-searchable-pdf-pipeline
```

へ変更しました。

改名前には保全tagを作り、実行コードに残る旧固定パスを相対化しました。比較実験用コードは削除せず、開発史・再現資料として残しました。

この改名は「完全安定版になった」という宣言ではなく、**repository名を実態へ合わせるための変更**でした。

## 11. 改名でvenvが壊れ、再構築可能性の重要性が見えた

ローカルフォルダ名を変更した直後、`.venv_paddle/bin/python` が利用できなくなりました。

Python venv内部には作成時の絶対パスを含む場合があり、フォルダを移動・改名しただけでも壊れ得ます。

この事故を受けて、環境そのものを長期保存するより、**環境を再構築できる情報を保存する**方向へ進みました。

```text
requirements-paddle.txt
tools/rebuild_paddle_venv.sh
```

を追加し、当時の主要環境、

```text
Python 3.10.4
paddleocr 3.7.0
paddlex 3.7.1
onnxruntime 1.23.2
numpy 2.2.6
```

を再構築しました。

改名後も既存JSONを再利用し、通常版・圧縮版とも3194文字を抽出できることを再確認しました。

## 12. 生PaddleOCR JSONが5ページで数GBになった

次に、workspace容量の監査から別の設計問題が見つかりました。

PaddleOCRの生結果をそのままJSON化すると、OCR後段には不要な入力画像配列等まで含まれ、1ページ約192MBになる例がありました。

5ページ試験では、

```text
ページJSON合計: 約961.3 MiB
統合JSON:       約1.2 GB
ジョブ全体:     約2.4 GB
```

まで膨張していました。

検索可能PDFや統合テキストのために本当に必要なのは、主として

```text
text
confidence
bbox
polygon
```

です。

そこで `compact-v1` JSONへ移行しました。

既存5ページ結果の変換では、

```text
ページJSON合計: 961.3 MiB → 129.3 KiB
統合出力:       約1.4 GB → 916 KiB
ジョブ全体:     2.4 GB → 15 MB
統合所要時間:   47.86 s → 0.04 s
```

となりました。

compact化後も、OCR文字、bbox、searchable PDF、フォントフォールバック、圧縮後テキスト保持に必要な機能は維持されました。

これは単なる容量削減ではなく、**再実行可能な中間形式として何を保存すべきか**を明確化した設計変更でした。

## 13. 使わない生成物も、削除理由・残す理由を記録する

compact化と同時にworkspaceを整理しました。

旧実験用出力、壊れたvenv、重複出力等を整理する一方で、`jobs/` は単なるcacheとして一律削除しないことにしました。ページ別compact JSONが残れば、OCRをやり直さずに、

- PDF renderer
- font fallback
- compression
- verification

だけを改善・再検証できるためです。

比較実験の成果物も、削除ではなく別archiveへ退避しました。

この経験から、「Git管理外＝不要」「`git status` がclean＝ローカルに重要データがない」という理解を避ける方針が生まれました。

## 14. 人間とChatGPTの双方が忘れることを設計要件にした

workspace整理後、利用者から「なぜこのファイルが残っているか、生成時に何をしたかも忘れる。新しいChatGPT chatへ移ればAI側も忘れる」と指摘がありました。

そこでprivate側では、**恒久的なプロジェクト記憶文書**と**新しいチャット向けの短い引き継ぎテンプレート**を作成しました。

恒久記憶文書には、たとえば次を記録しました。

- 主要ファイルの役割
- Git管理外ファイルを残す理由
- 外部依存
- 削除してよいもの / いけないもの
- compact-v1
- job名再利用の注意
- 既知の警告
- shell固有の事故
- 未検証事項

短い引き継ぎテンプレートには、新しい会話で最初に確認すべき正本と、直前の成功状態・未完了作業を伝える欄を設けました。

この時点から、**将来忘れそうな設計理由をコード変更と同じ作業単位で文書へ残す**こと自体を開発方針にしました。

## 15. 43ページ実資料で一連の工程を確認

5ページだけでなく、約43ページの実資料でも、

```text
PDF前処理
→ ページ画像化
→ PaddleOCR
→ 統合成果物
→ ページ別searchable PDF
→ 結合PDF
→ テキスト検証
→ 150dpi圧縮
```

まで完走しました。

通常版・圧縮版の双方から**34,433文字**を抽出し、保持率1.000を確認しました。

同じ資料での概算容量は、

```text
source PDF:                   about 5.2 MB
PaddleOCR searchable PDF:     about 39.9 MB
PaddleOCR 150dpi PDF:         about 18.5 MB
NDL pipeline 150dpi PDF:      about 28.6 MB
```

でした。

この結果から、元PDFの容量だけに追従するのではなく、検索可能性、画質、Unicode保持、処理の単純さを含めて圧縮設計を評価する方針を維持しました。

## 16. 70ページ資料が「OCR文字0件は正常」という要件を教えた

70ページの絵画目録PDFでは、PaddleOCR自体は全70ページを処理し、統合成果物も生成できました。

しかしsearchable PDF rendererは7ページ目の

```text
lines=0
chars=0
```

をエラーとして停止しました。

絵画、写真、空白主体のページならOCR文字が0件でも正常です。アーカイブ用途でそのページを削除すると、原資料のページ数・順序・内容を破壊します。

そこでrendererを変更し、

```text
OCR文字あり
→ 原画像 + 透明Unicode text

OCR文字なし
→ 原画像のみのPDF page
```

としました。

さらに空OCR JSONを使った回帰テストを追加し、「文字がなくてもページは残る」ことを仕様として固定しました。

## 17. ここまでで成立した設計原則

2026年6月21日の一連の開発をまとめると、最終的に次の原則が明確になりました。

### 成功は「処理が終了した」ことではなく、成果物を検証して決める

```text
OCR終了
≠ 成功

PDF生成
≠ searchable PDF成功

Ghostscript終了
≠ 圧縮版成功
```

抽出テキスト、ページ数、必要に応じて圧縮前後の内容まで確認して初めて成功とします。

### OCRと後処理を分離する

ページ別compact JSONを境界にすることで、OCRを再実行せずにPDF・font・compressionだけを改善できます。

### 利用者が停止と誤解する時間を放置しない

実用品では速度だけでなく、何をしているか分かることも重要です。初期化・統合・長時間工程へ進捗表示を追加しました。

### 原ページが正本である

OCR文字0件でもページを消さず、検索文字が不完全でも元画像を表示面として残します。

### 環境や記憶も再構築可能にする

venvそのもの、ローカル生成物、一つの会話履歴だけへ依存せず、requirements・履歴・恒久記憶・引き継ぎ情報を残します。

## 18. 後のpublic版へつながったもの

この6月のhardeningで成立した次の考え方は、その後のpublic releaseにも引き継がれました。

```text
PDF/imageを一つの入口から処理
OCR-safe preprocessing
PaddleOCR / ONNX Runtime
per-page compact JSON
image-preserving searchable PDF
character-level font fallback
post-compression text verification
zero-text page preservation
reproducible setup
```

2026年9月のpublic版準備では、さらにフォント配布・CJK補助面・ReportLab ToUnicode CMap・fresh setup等を再検証し、現在の `M PLUS → Jigmo → Jigmo2 → Jigmo3` 構成へ更新しました。

したがって、現在のrepositoryは単にPaddleOCRを呼び出すwrapperではなく、**実資料を処理する中で発生した失敗を一つずつ仕様へ変換した結果**として現在の形になっています。

---

OCRエンジン選定までの前史は [OCR選定史補遺](OCR_SELECTION_HISTORY_SUPPLEMENT.md) を、現在の全体像は [開発背景と設計判断](DEVELOPMENT_BACKGROUND.md) を参照してください。
