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

`hermes-desktop-light/v0.22.0-r1`と`other-app/v0.22.0-r1`は別Releaseとして共存する。
将来のアプリも`scripts/distribution.py`の識別・比較ルールを利用し、アプリ固有のビルド、ライセンス検査、受け入れ検証、公開ゲートを別に持つ。
ここでの他アプリ名・バージョンは説明例であり、配布物やmanifestを作成するものではない。

公開用workflowのconcurrencyはアプリ単位にする。mainへの書き戻しは最新mainから生成し、競合したら再試行する。force-pushしない。他アプリのmanifestを変更しない。
各アプリのcheckverは公開URL・SHA256検証後に書き戻された自身のmain manifestを参照する。APIのRelease一覧のページ数・他アプリの公開順・未公開上流版には依存しない。

## Hermes Desktop Lightの改訂

通常の安定版追従は`r1`。公開済みの同じ上流版を修正する場合、信頼済みmainの手動workflowの`revision`に`2`などを指定する。
対象はその時点の最新対応安定版。過去上流版を指定してのバックポートビルドは現在の自動化の対象外。
改訂番号は正の整数で、先頭ゼロを許可しない。既存manifest以上の版がなければskipし、定期実行が`r2`を`r1`へ戻すことはない。
番号は承認済み修正のために管理者が指定するもので、CI再実行数から自動採番しない。公開ゲート`HERMES_DESKTOP_LIGHT_RELEASE_ENABLED`は引き続き既定で無効。

## Hermes Desktop Lightの開発channel（policy A）

- `bucket/hermes-desktop-light.json`は、Light対応stable Releaseがこのアプリ用に初めて
  build・Windows検証・公開されるまで、単一の開発channelを追従する。開発版は必ず
  **DEVELOPMENT BUILD — NOT STABLE** と表示する。開発publisherのゲートは
  `HERMES_DESKTOP_LIGHT_DEV_RELEASE_ENABLED`で、stable gateとは別に既定で無効。
- 開発版は upstream `main`をworkflow開始時に解決した完全なcommit SHAへpinし、
  そのSHAにidentityとmanaged builderのLight contractがある場合だけbuildする。
  exact commitのMIT LICENSE本文を検査し、SHA256を`provenance.json`とRelease bodyに記録する。
- versionは`0.0.0-alpha.dev.<devSeq>-r<revision>`。開発tagは`<app>/dev/v<version>-<40桁SHA>`（Hermesでは
  `hermes-desktop-light/dev/v<version>-<40桁SHA>`）、ZIPは
  `hermes-desktop-light-dev-<version>-<40桁SHA>-windows-x64.zip`とする。これは安定版の
  `<app>/v<ver>-rN`ルールとは別namespaceであり、同じアプリのdev prereleaseとstable Releaseを
  同時に保持できる。Scoopの`Compare-Version`でdevSeq・revisionは数値順になり、全dev versionは
  `0.0.0-r1`および将来のstable versionより小さい。`devSeq`は公開済みの
  `hermes-desktop-light/dev/` Releaseから最大値+1として算出する（mutableな外部counterは持たない）。
  Scoopのnamed capture placeholderは実装の`ToTitleCase`に合わせ、camel-caseの`shortSha`を
  `$matchShortsha`として記述する（pointer JSONのキーは`shortSha`のまま）。`$matchVersion`、
  `$matchCommit`、`$matchShortsha`はpointerの検証済み値だけから生成する。
- 同一upstream commit・同一build conditions fingerprint（bucketのbuild/verify workflowと
  scripts、upstream ref/variant/target、runner/Python、builder args、compression、signing、
  local payload、bundle環境ハッシュを含む）のschedule再実行は同じversion/tag/assetsを再利用し、
  revisionを増やさない。条件が変わった同じcommitの配布修正は、明示的な`workflow_dispatch`
  の`revision=2`以降だけ許可する（r2+をscheduleから生成しない）。異なるcommitはr1から開始する。
  公開済みReleaseのassetを上書きせず、draft中の異なるbytesも拒否する。
- scheduleはstable gateが有効で、upstream stableがLight identity、managed builder、annotated
  claim admissionを満たす場合だけstable buildを計画する。それ以外はdevelopmentを計画し、
  選択channelのgateが無効ならbuildをskipしてrunnerを起動しない。stable buildが失敗/skipして
  stable Releaseがまだ公開されているわけでない場合、dev manifestは維持する。
- PRはbucket Release一覧を参照せず、pinしたupstream main commitのdevelopment build/smoke、
  exact MIT gate、conditions fingerprintをread-onlyで検証する。publish/writebackはしない。
- Light stable Releaseが公開されるtransitionは一方向で、`metadata/hermes-desktop-light-channel.json`
  にstable version/tag、upstream commit、artifact SHA256を記録する。以後、stable publisherだけが
  `bucket/hermes-desktop-light.json`を更新し、開発publisherはそのmarkerまたはこのappのstable
  Releaseを検出してhard-refuseする。stable Releaseが実際に公開されるまでmanifestを自動切替せず、
  channelをbounceしない。

## 公開と過去版

read-onlyのビルド・検証と、上流コードを実行しない公開ジョブを分離する。
DraftにZIP・provenance・その版の`hermes-desktop-light.json`を揃え、公開後の実URLからZIPのSHA256を確認してから最新版manifestとREADMEを更新する。
失敗時は最後の正常なmanifestを維持する。公開済みReleaseへの再実行は既存の検証済みバイト列を再利用する。
過去版ZIPはReleaseから直接ダウンロードできる。添付manifestはURLとSHA256を固定するが、checkverは最新版の案内を参照する。Scoopでの過去版導入・固定・ダウングレードは別途実Windows検証が必要で、今回完了とは扱わない。
重大な安全上・権利上の問題では配布停止を優先する。通常の保持方針は危険な成果物を永久に配布する約束ではない。

## 公開前の条件

対象タグと同梱物のライセンス・著作権表示・第三者通知、名称と非公式配布表示を確認する。
各アプリのWindows実行・必要ランタイム・更新移行を検証する。Hermes Desktop Lightのgateway接続・認証移行などの既存阻害条件はこのルール変更で解消したとは扱わない。
マージ・公開有効化・実Release作成は別途承認する。
