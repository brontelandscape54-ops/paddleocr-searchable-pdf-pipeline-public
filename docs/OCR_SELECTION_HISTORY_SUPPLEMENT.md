# OCR選定史補遺 — Marker / NDL / Yomitoku / PaddleOCR

[日本語] | [English](OCR_SELECTION_HISTORY_SUPPLEMENT_en.md)

この文書は、[開発背景と設計判断](DEVELOPMENT_BACKGROUND.md) を補うための開発史補遺です。

2026-05-31〜06-21の保存チャット、当時のターミナルログ、比較スクリプトと生成物を再確認した結果、PaddleOCR中心の本番構成へ至る途中に、公開用開発背景ではまだ十分に見えていなかった重要な分岐が確認できました。

以下の記述は、特定の開発資料・当時の機材・設定に対する記録です。一般的なOCR性能ベンチマークではありません。

## 1. 比較対象の中心は横書き活字の表資料だった

Marker searchable PDFの初期成功時、対象について「表になっている資料は基本的に横書きの活字」と確認していました。

したがって、Marker / NDL / Yomitoku / PaddleOCR の比較で得たセル数・文字数・類似度・速度等は、主として**横書き活字の日本語文献一覧・表資料**を対象とした開発記録です。

この比較だけから、次の性能を一般化することはできません。

- 縦書き表
- 手書き表
- 崩し字
- 写真・図版主体の表
- 複雑な多段組表

現在のpipeline自体はより広い資料を入力できますが、「Markerとの比較でPaddleOCRを選んだ」という部分の実証範囲は上記の横書き活字資料を中心としています。

## 2. PaddleOCRへ直行したのではなく、一度NDLOCR-Liteを主認識器にする案が本命になった

MarkerのOCRを無効にすると表構造・セル座標は高速に取得できることが分かり、文字認識だけ別OCRへ任せる方針が成立しました。

この時点で、直ちにPaddleOCRを主認識器へ決めたわけではありません。

当時の実資料では、NDLOCR-Liteの文字認識精度が最も高いという利用経験があり、2026-06-20には次の構成を本命案として検討しました。

```text
Marker
  → 表領域・行・列・セル座標

NDLOCR-Lite
  → ページ全体の文字認識

座標統合
  → NDLの文字領域をMarkerセルへ割り当て

Yomitoku風レンダラー
  → 既に調整してきた透明テキスト配置方式を利用

searchable PDF
```

この案は、2026年4月に行っていた別の実験、すなわち

```text
NDLOCRの文字列
+
Yomitokuのより細かな座標・PDF配置
```

を組み合わせるsearchable PDF開発の延長線上にあります。

当時、NDLOCRは文字列の品質がよい一方でbboxが粗く、Yomitokuはより細かな配置情報とsearchable PDF生成ロジックを持つ、という役割分担を検討していました。その経験が、6月の「OCR・構造認識・PDF配置を別部品として考える」設計へつながりました。

このため、開発史を単純に

```text
Marker → PaddleOCR
```

と表現するのは正確ではありません。より実態に近い流れは、

```text
Marker単独
→ Markerを構造認識と文字認識へ分解
→ Marker + NDLOCR-Lite + Yomitoku風配置を検討
→ NDL / Yomitoku / Marker / PaddleOCRを同一資料で比較
→ PaddleOCR単独でも十分なtext + bboxを得られると確認
→ 本番構成をPaddleOCR中心へ簡素化
```

です。

## 3. PaddleOCRは当初「軽量な代替候補」だった

NDLOCR-Liteを主認識器とする案を検討した時点では、PaddleOCRは必ずしも第一候補ではありませんでした。

PaddleOCRを追加比較した理由の一つは、MarkerのSurya文字認識に代わる**軽量な日本語OCR候補**として、文字列だけでなくbboxも得られる可能性があったためです。

その後、同一ページで5方式比較を行い、PaddleOCR smallが214領域を約3.81秒で処理した記録や、Markerとの全文文字列類似度0.862などを確認しました。ただし、この段階でも全文類似度をOCR精度とはみなさず、原画像付きセル比較へ進んでいます。

最終的にPaddleOCR中心へ移ったのは、「一般にNDLより高精度だと証明された」からではありません。

最終要件で必要だった、

```text
実用的な文字認識
+
十分細かなbbox
+
高速・ローカル処理
+
原画像保持型searchable PDFへ直接使える中間データ
```

を一つのOCR工程から得られ、Marker・NDL・Yomitokuを常時組み合わせるより本番パイプラインを単純化できたためです。

## 4. MarkerのTableCell表現を再確認すると、168セルとは別に231セルの比較枠が得られた

初期のlayout-only試験では、Markerから約4秒で168セルの座標を取得し、この168セルを最初の画像付き比較フレームとして使いました。

その後、通常converterでOCRを含むMarker出力を詳しく確認すると、別の `blocks.json` では次の構造が得られました。

```text
block_type 27 (TableCell): 231
block_type 1  (Line):        2
block_type 22 (Table):       1
```

231セルは、対象表の

```text
21行 × 11列 = 231セル
```

に対応していました。

また、この時点のMarkerでは、旧来のSpan形式の `text` を読むだけでは文字が取れず、TableCellの `text_lines` に認識文字が入る形式へ変わっていることを確認しました。

TableCell対応版のsearchable PDF生成では、一例として次を得ました。

```text
TableCell:   212 text items
characters: 815
```

生成結果を確認した際にも、認識精度について「やはり精度はよい」と評価しています。

したがって、Markerの評価を「168セルの実験」だけで代表させるのも不十分です。

## 5. 168セルと231セルは矛盾ではない

168セルと231セルは、同じMarker出力を二通り数えた値ではありません。

- **168セル**: OCRを無効にしたlayout-only系の試験で得たセル座標。高速な構造検出と最初の空間比較に利用。
- **231セル**: OCRを含む別のMarker `blocks.json` で得た明示的なTableCell群。21×11の表構造として後から精査。

処理モード・出力表現・当時のMarker側データ構造が異なるため、両者は別の開発段階の記録です。

この区別を明記しておかないと、「Markerのセル数が168なのか231なのか」という見かけ上の矛盾が生じます。

## 6. 231セル版の比較ビューへ発展

231個のMarker TableCellを比較基準として、`compare_ocr_cells_marker231.py` を作成しました。

この比較では、

```text
Marker
  → blocks.json の各 TableCell.text_lines

Yomitoku-lite / Yomitoku-full
  → Markdown表を21行×11列へ対応

NDL / PaddleOCR
  → 文字bboxをMarkerの各TableCellへ空間的に割り当て
```

という方式を採りました。

生成物は次のような構成でした。

```text
ocr_cell_comparison_marker231.csv
ocr_cell_comparison_marker231.html
ocr_cell_comparison_marker231_assets/
```

HTMLでは、原画像セル、Marker、Yomitoku-lite/full、NDL、PaddleOCR、Markerとの文字列類似度、PaddleOCR confidence、全一致・多数一致・空欄・相違等を確認できるようにしました。

これは、評価方法が

```text
全文文字数
→ 全文文字列類似度
→ 168セル画像付き比較
→ 231個の明示的TableCellを使った比較
```

へ段階的に精密化したことを示しています。

## 7. 開発史上の結論

今回の追加確認を含めると、PaddleOCR中心の本番構成へ至る経緯は次のように整理できます。

```text
NDL / Yomitokuで表資料に課題
→ Azure Document Intelligenceは高品質だが継続費用が難しい
→ Markerを試し、認識品質は非常に良好
→ Marker出力からsearchable PDF自作にも成功
→ 複数ページではMarker文字認識が重く、MPS OOMも発生
→ OCRmyPDF / Tesseractは軽いが対象資料で精度不足
→ Markerを「構造」と「文字認識」に分解
→ layout-only Markerは高速
→ まずMarker + NDLOCR-Lite + Yomitoku風配置を検討
→ PaddleOCRを軽量OCR候補として追加
→ 文字数・全文類似度・168セル・231 TableCellへ評価を精密化
→ PaddleOCR単独で実用的なtext + bboxを取得可能と判断
→ 最終成果物が表構造再構築ではなく原画像保持型searchable PDFだったため、PaddleOCR中心へ簡素化
```

ここで重要なのは、最終選択が単純な「OCR精度ランキング」の結果ではないことです。

精度、処理負荷、bboxの粒度、searchable PDFへの接続しやすさ、依存関係、保守性、そして「原画像を資料として保持する」という最終成果物の要件を合わせて判断した結果です。
