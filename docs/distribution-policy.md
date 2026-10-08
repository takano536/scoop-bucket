# ビルド済みアプリの配布ルール

[この変更の実行済み検証と未確認事項](distribution-validation.md)

この文書は、このbucket自身が上流ソースからビルドしてGitHub Releasesへ配布する
bucket-built distributionに適用する。`bucket/UDEVGothic-NF.json`のように上流が
公開したバイナリを参照する通常のScoop manifestには、この文書の改訂番号・公開ゲート・
provenance・ライセンス/著作権/第三者通知ゲートを一律には適用しない。通常のmanifestは
上流のversion、checkver、autoupdate、ライセンス表示に従う。

## 名前と正本

- アプリごとにReleaseタグを`<app>/v<upstream>-r<N>`とする。
- Scoop versionとZIP名にも同じ配布改訂番号を含める。初回は`r1`。
- 同じ上流版の修正だけ改訂番号を増やす。通常の再実行では増やさない。
- 上流タグ・commitと配布版を区別する。`r2`でもビルド対象は同じ上流タグであり、
  上流に存在しないタグを要求しない。
- 公開済みアセットは上書きしない。修正版は別Releaseとし、過去のZIP・provenance・
  版固定manifestを保持する。
- 各配布版の正本はそのReleaseのアセット。最新版の案内は`main`のアプリ別manifestで
  あり、リポジトリ全体のLatest Releaseは使用しない。
- ZIPはGitにcommitしない。Actions Artifactsは一時検証用で、Scoopの配布URLには使用
  しない。

## 上流版とアプリ固有契約

- ビルド前に、対象アプリの契約で定めた上流tag/commit、version形式、source/build条件、
  claimまたはadmission条件、外部サービスなどの実行条件を確認する。これらを他の
  アプリへ推測で適用しない。
- `scripts/distribution.py`の現行version helperは、数値3要素の上流版と`rN`を使う
  契約だけを受け付ける。これは現在対応している形式の実装であり、CalVerや4要素版を
  含むすべてのアプリに使える汎用parserではない。別形式のアプリは固有parserと回帰
  テストを持つ。
- 公開用workflowは計画後にも、各アプリの契約に従ってRelease状態、タグcommit、
  source/build identity、claim/admission記録を再検証する。計画後に対象が動いた成果物は
  公開しない。対象外または契約不成立は、理由を記録した明示的なskipまたは失敗にする。

## 複数アプリ

`<app-a>/v<upstream>-r1`と`<app-b>/v<upstream>-r1`は別Releaseとして共存する。
各アプリは固有のビルド、ライセンス検査、受け入れ検証、公開ゲートを持ち、共通ルールは
それらの契約を置き換えない。

公開用workflowのconcurrencyはアプリ単位にする。`main`への書き戻しは最新`main`から
生成し、競合したら再試行する。force-pushしない。他アプリのmanifestを変更しない。
各アプリのcheckverは公開URL・SHA256検証後に書き戻された自身のmain manifestを参照する。
APIのRelease一覧のページ数・他アプリの公開順・未公開上流版には依存しない。

## 公開と過去版

read-onlyのビルド・検証と、上流コードを実行しない公開ジョブを分離する。
DraftにZIP・provenance・その版の`<app>.json`を揃え、公開後の実URLからZIPのSHA256を
確認してから最新版manifestとREADMEを更新する。
失敗時は最後の正常なmanifestを維持する。公開済みReleaseへの再実行は既存の検証済み
バイト列を再利用する。
過去版ZIPはReleaseから直接ダウンロードできる。添付manifestはURLとSHA256を固定するが、
checkverは最新版の案内を参照する。Scoopでの過去版導入・固定・ダウングレードは別途
実Windows検証が必要で、今回完了とは扱わない。
重大な安全上・権利上の問題では配布停止を優先する。通常の保持方針は危険な成果物を
永久に配布する約束ではない。

## 公開前の条件

対象tagと同梱物のライセンス・著作権表示・第三者通知、名称と非公式配布表示を確認する。
各アプリのWindows実行・必要ランタイム・更新移行・外部サービス接続などの条件を、
アプリ固有の契約に従って検証する。
マージ・公開有効化・実Release作成は別途承認する。
