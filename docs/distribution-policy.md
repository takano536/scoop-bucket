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
- `scripts/distribution.py`のHermes Desktop Light helperは、公式Desktopの4要素product
  version（例`26.1009.7.410`）を受け取り、`<desktop>-alpha.dev.1-r<N>`を生成する。
  既存の`0.0.0-alpha.dev.1-r1`も比較でき、通常のScoop更新で新形式へ進める。
  他のアプリ・CalVer・stable versionを推測でこのhelperへ渡さない。

## 複数アプリ

`<app-a>/v<upstream>-r1`と`<app-b>/v<upstream>-r1`は別Releaseとして共存する。
各アプリは固有のビルド、ライセンス検査、受け入れ検証、公開ゲートを持ち、共通ルールは
それらの契約を置き換えない。

公開用workflowのconcurrencyはアプリ単位にする。`main`への書き戻しは最新`main`から
生成し、競合したら再試行する。force-pushしない。他アプリのmanifestを変更しない。
各アプリのcheckverは公開URL・SHA256検証後に書き戻された自身のmain manifestを参照する。
APIのRelease一覧のページ数・他アプリの公開順・未公開上流版には依存しない。

## Hermes Desktop LightのDesktop-release policy

Hermes Desktop Lightは、upstreamのGitHub `main` commitを追従する配布ではない。
scheduled runは、公式R2 AppInstaller feed
`https://hermes-assets.nousresearch.com/releases/win32/canary/canary.appinstaller`
をDesktop-release detectorとして読む。feedの`MainBundle/@Version`とMSIX URLが同じ
4要素product versionであることを確認し、Windows packageのHEAD size/ETagを記録する。
commit-onlyの`releases/commit/<sha>/`成果物、agent-only GitHub Release、通常のmain進行、
draftだけのタグ、同じfeedの再観測はDesktop releaseではない。現在自動検出する公式配布経路は
Windows canary feedだけであり、将来のofficial stable Desktop channelはこのdetectorでは
自動検出しない。manifestのcheckver regexも`-alpha.dev.`だけに一致する。

feed versionから、公式のcanary tag timestamp（例:
`26.1009.7.410` → `v0.21.6+canary.20261009T070410Z`）をupstream tags APIで一意に
検索する。そのannotated tagの`git/ref/tags/<tag>`、`git/tags/<object-sha>`が同じ
完全commitへ解決することを必須とする。さらにR2のimmutable
`releases/tag/<tag>/handoff-windows-universal.json`、`metadata-windows-x64.json`、
tag archive packageを読み、feedのversion/sizeとcommitを突き合わせる。いずれかを
一意に結び付けられないAPI/metadataエラーは、unsupportedとは別の失敗（non-zero）である。
公式配布源URL、Desktop version、canary tag、upstream commit、package SHA/ETag、
bucket-side build commitをRelease bodyと`provenance.json`へ記録する。

Desktop sourceが`apps/desktop/product-identity.cjs`のLight identityとmanaged builderの
Light contractを持つかは、Desktop-release detectionの後にexact commitで判定する。
対応しないsourceは理由付き`unsupported` skip（exit 0）とし、current manifestを変更せず、
mainへフォールバックしない。API障害、tag ambiguity、handoff不整合は必ず失敗させる。
upstream sourceのcanary/development性と、bucketが配布する**unofficial Light build**で
あることは別の属性である。

Scoop versionは`<desktop-version>-alpha.dev.1-r<N>`（例:
`26.1009.7.410-alpha.dev.1-r1`）。これは既存の`0.0.0-alpha.dev.1-r1`より大きく、
同じDesktop versionでは`r1 < r2`、未来のstable product versionよりalpha.dev buildが
小さい。初回Desktop releaseはr1、同じpublished Desktop buildと同じbuild conditionsの
再実行は同じversion/tag/assetsを再利用してno-opにする。r2以降は同じsourceを修正する
承認済み手動dispatchだけで指定し、公開済みassetを上書きしない。

保持する条件は既存と同じである。exact Windows build、Light payload、MIT license、
third-party notices、native launch/remote gateway acceptance、artifactと公開URLのSHA256
検証を行う。失敗・unsupported skipでは現在のinstallable versionを保持する。
Releaseはcanary由来のunofficial prereleaseとして別tagに作成し、既存Release/past versionを
変更しない。公開gateは既存の`HERMES_DESKTOP_LIGHT_DEV_RELEASE_ENABLED`で制御し、このポリシー
では設定値を変更しない。

checkver/autoupdateはbucketが実際に公開したLight versionの
`metadata/hermes-desktop-light-release.json` pointerとimmutable Release URL/SHA256を参照
する。公開前のbuild/acceptanceと公開/writebackは分離し、公開後にのみmain manifestとREADME
を更新する。

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
Hermes Desktop Lightのgateway接続・認証移行などの既存阻害条件は、このルール変更で解消したとは扱わない。
マージ・公開有効化・実Release作成は別途承認する。
