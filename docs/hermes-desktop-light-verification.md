# Hermes Desktop Light 検証

共通の[配布ルール](distribution-policy.md)と[検証記録](distribution-validation.md)を前提に、Hermes Desktop Light固有の上流・Light・gateway契約と、実行済みCIの結果を記録する。

## Hermes Desktop Light固有の契約

- 安定版として扱う上流タグは、上流の`STABLE_TAG_RE`と同じ`vX.Y.Z`形式のSemVerだけとする。Draft・Prerelease・canary・歴史的CalVerは対象外である。
- 上流のstable-release toolingが作るclaimと、公開時の安定タグ本文に入るreceiptを検証する。Release状態、タグから解決したcommit、claimのversion・commit・tag情報が一致しないものはadmissionしない。
- sourceのLight identityと管理されたLight builderの対応ファイルを検査し、非対応や必要ファイルのないcommitは理由を記録してskipする。API障害や権限エラーはskipと混同せず失敗させる。
- 配布物はリモート専用のLight構成で、既存のHermes gatewayへの接続を必要とする。起動smokeだけではgateway接続、認証・接続設定の移行、Lightのローカル実行可否を証明しない。これらはWindowsで別途受入確認する。

## 個別検証の入口

共通のローカル手順は[検証手順](verification.md)から実行する。Hermes Desktop Light固有のNode.js smokeスクリプトは、次で構文を確認する。

```bash
node --check scripts/smoke-hermes-desktop-light.cjs
```

PythonのHermes Desktop Light・配布契約テストは、共通の`unittest discover`に加えて、必要なら次のように個別実行できる。

```bash
python3 -m unittest discover -s tests -p 'test_hermes_desktop_light*.py' -v
python3 -m unittest discover -s tests -p 'test_distribution.py' -v
```

## Hermes Desktop Light workflow

[`hermes-desktop-light.yml`](../.github/workflows/hermes-desktop-light.yml)は、UTCの4時間ごとのschedule、`workflow_dispatch`（`revision`入力）、および関連ファイルを変更したPull Requestで起動する。`plan`はUbuntuで個別テストと`hermes-desktop-light.py plan`をread-only実行し、Light対応と対象を決める。対象がある場合だけ`build`がWindows runnerでビルド・smokeを実行し、`hermes-desktop-light-windows-x64` artifactを作る。

`publish`はchannelごとの明示gate（developmentは`HERMES_DESKTOP_LIGHT_DEV_RELEASE_ENABLED`、stableは
`HERMES_DESKTOP_LIGHT_RELEASE_ENABLED`が`true`）、scheduleまたは`workflow_dispatch`、
`refs/heads/main`、build対象をすべて満たす場合だけ実行する。PRではdevelopment plan/buildの
read-only検証だけを行い、publishは実行しない。公開済みassetの再検証とRelease公開、
manifest・READMEのmain書き戻しを行うpublishの詳細なゲートと未確認事項は、この文書の公開ゲート節に従う。

### 改訂

stableの通常追従は`r1`から始める。公開済みの同じ上流版を修正する場合は、信頼済みmainの手動workflowの`revision`に`2`などを指定する。対象はその時点の最新対応安定版であり、過去上流版を指定してのバックポートビルドは現在の自動化の対象外である。
developmentの新しい上流commitも`r1`から始める。developmentは実行時のupstream `main`を完全な40桁commitへ解決し、同じcommit・同じ
conditions fingerprintなら既存Release/assetを再利用する。条件が変わった同じcommitは
scheduleでは`build=false`のno-opとし、明示的なworkflow_dispatchでのみ`r2`以降を許可する。
改訂番号は正の整数で先頭ゼロを許可せず、CI再実行数から自動採番しない。Stableのtag/claim
admission、gateway接続・認証移行などの阻害条件は、改訂番号を増やしただけでは解消したと扱わない。公開ゲートは既定で無効のままとする。

## 実Windows CI
以下の既存preview記録はPR #7/#8およびPR #6導入前の履歴であり、現在のdevelopment
channelのlicense/notice gateを通過した成果物の証拠ではない。

## 実Windows CI: run 37738844817

[Hermes Desktop Light run 37738844817](https://github.com/takano536/scoop-bucket/actions/runs/37738844817)を、PR #8のhead `90b05923687d846397fbab287b91b51d9ab60f81`に対する`pull_request`イベントで実行した。`plan`・`build`・`acceptance`はsuccess、`publish`はskippedだった。

Actionsのcheckoutログで、ビルドjobが実際にcheckoutしたbucketのPR merge refは`3acdfc472b635fac6a382c51c1b5e03e6963dc10`（`90b05923687d846397fbab287b91b51d9ab60f81`を`1bccbc5ec3f093348c2e13b1fd09b32a8ecae91e`へmergeしたcommit）である。したがって、runのhead SHAと、PR検証用のmerge refを区別して記録する。上流checkoutは`NousResearch/hermes-agent@a3ed4a173070e981332e4d879ff6cc8b9efd57ab`だった。

### 成果物とprovenance

## Development channelの現在の計画結果

- [Hermes Desktop Light run 37779700289](https://github.com/takano536/scoop-bucket/actions/runs/37779700289)では、
  planが`development`を選び、上流`NousResearch/hermes-agent@25a71a744cb9ef06950a91638e6229b4f808d461`
  を完全な40桁SHAへ解決した。versionは`0.0.0-alpha.dev.1-r1`、conditions fingerprintは
  `9223aa09872794c9b7ceac52d7c871c0fbbfaeaceddad19a1ce20908f3801309`である。
- buildはPR #6のstrict license/notice gateで停止した。未解決は
  `lazy-val@1.0.5`、`react-remove-scroll-bar@2.3.8`、`unicode-animations@1.0.3`、
  `use-composed-ref@1.4.0`で、acceptanceとpublishは実行されなかった。このrunから
  Windows受入成功やRelease公開を推論しない。
- 同じupstream commit・同じconditions fingerprintの再実行は既存成果物を再利用し、
  条件変更時のscheduleはno-op、明示的なworkflow_dispatchだけが`r2+`を作る。


## 成果物の保存先とskip条件
- build artifact [`hermes-desktop-light-windows-x64`](https://github.com/takano536/scoop-bucket/actions/runs/37738844817/artifacts/11533625401): **170,080,519 B**。
- acceptance artifact [`hermes-desktop-light-windows-acceptance`](https://github.com/takano536/scoop-bucket/actions/runs/37738844817/artifacts/11532849103): **15,753 B**。
- 上流: `NousResearch/hermes-agent@a3ed4a173070e981332e4d879ff6cc8b9efd57ab`。
- acceptanceのgateway preflightが報告した上流アプリversion: `0.21.5`。
- provenanceの配布version: `preview-a3ed4a1`。acceptanceの`bucketPackageVersion`は`preview`であり、安定版versionではない。
- ZIP: `hermes-desktop-light-preview-a3ed4a1-windows-x64.zip`。
- ZIP SHA256: `cd577d5789cbaefecf4750cf580ea940e86ff659bba0953470fb9d4779780c3c`。
- `provenance.json`の`run`は上記run URL、`payload`は`light`、`updateMechanism`は`external`、実行ファイルはupstream commitのpreview executable、署名ラベルは`unsigned unofficial build`である。これはAuthenticodeの測定結果ではなく、build/acceptanceで`Get-AuthenticodeSignature`・`signtool`・証明書結果を取得していないため、公開artifactの署名状態は未確認である。provenanceのSHA256とacceptanceの`artifactSha256`は一致する。
- provenanceのsmoke記録は、native launchを2回実行し、rendererのloadとlocalStorage保持を確認したものだった。これはPR用preview artifactであり、GitHub Releasesへの公開やmanifest登録は行っていない。

### acceptance artifactの内容と実際に確認したこと

acceptance artifactには`acceptance.json`、`before.json`、`after.json`、`scoop-update-evidence.json`、`runtime-evidence.json`、gateway/HTTPログが含まれ、`acceptance.json`のstatusは`passed`だった。test-onlyの`hermes-desktop-light-acceptance.json`を使ったdisposable local bucketで、次を確認した。

- Scoopのbefore versionは`0.0.0-test-before-a3ed4a1`、after versionは`0.0.1-test-after-a3ed4a1`。manifest/install version、resolved `current` target、Start Menu shortcutのresolved targetを読み戻し、版切替assertionとno-op拒否がpassedになった。afterの`current`とshortcutはafter versionの実行ファイルを指した。
- Scoop update後にStart Menuの`.lnk`経由で起動し、アプリとshortcutをuninstallで削除した。`HERMES_HOME`/Desktop user-dataは残った。
- before/afterともremote modeで、同じlocalhost gatewayへの接続設定とtokenSetを保持し、token自体はexportしなかった。after側ではpreload bridge経由のauthenticated `session.list` WebSocket RPCを実行した。別のdirect Node probeでは`/api/sessions?limit=1`の認証済みHTTPが200、誤secretが401だった。
- gatewayは上流の同じsource commitで`hermes serve --host 127.0.0.1 --port <ephemeral> --skip-build`として起動し、provider credentialは与えなかった。job内で生成したdashboard session tokenはmaskされた。
- Light ZIPに`resources/agent-payload`はなく、local backend probeは`bootstrap-needed`を返した。bootstrap/local agentは起動していない。画面にlocal-installのaffordanceがあっても、同梱local backendの実行を意味しない。
- updaterは`external`、checkは`reason=commit-build`、applyはunsupportedとして拒否され、app treeは不変だった。
- `runtime-evidence.json`はインストール済みapp treeの20ファイルを`dumpbin /DEPENDENTS`で検査した。runtime import 58件、API set probe 58件が記録され、58件はOS提供側に解決した。VC++ redistributable import、同梱runtime DLL、unparseable、unresolved、missing runtimeはいずれも0件で、`accepted`はtrueだった。

このrunのWindows runnerはGitHub-hosted環境であり、`runtime-evidence.json`の`runnerIsClean`はfalseである。runtime検査の受入結果は、クリーンなWindows consumer machineでのruntime独立性を保証しない。前提とする最小環境はElectronの対応最小環境であるWindows 10+であり、別途クリーン環境での確認が必要である。

### 何を更新検証したか

この受入run記録は過去のPR #8実装による履歴であり、現在のdevelopment buildの受入成功証拠ではない。
現行コードの最新development runは37779700289で、license gateによりbuildが停止し、acceptanceはskipされた。
before/afterは異なるtest-only versionを付けて**同じZIP（同じ名前・同じSHA256）を再インストール**したものだった。これはScoopのupdate path、`current`/shortcut切替、設定・認証保持、uninstallを検証するテストである。異なるupstream commitや異なるバイナリ間のmigrationを行ったものではなく、migrationの成功を主張しない。

## 失敗runの履歴

[run 37714650337](https://github.com/takano536/scoop-bucket/actions/runs/37714650337)は、旧workflowの`pull_request` runで、headは`be274390408caa73f1f79d89b96285b2c5662e9b`だった。`plan`と`build`はsuccess、`acceptance`はfailure（`Run Scoop and remote-gateway acceptance` step）、`publish`はskippedだった。このrunは履歴として保持するが、上記の成功runやruntime受入の証拠とは混同しない。

## PR #8 merge後のmain

PR #8のmerge commitは`2c4f4298160912f53faefd7b40cdc97f42a133f6`。このcommitの後に、workflow `Hermes Desktop Light`をbranch `main`で検索した結果は0件であり、merge後にmain上でHermes Desktop Light workflowが実行されたことは確認できなかった。

一方、同じmain commitに対して次のread-only workflowは成功した。

- [CI run 37740115916](https://github.com/takano536/scoop-bucket/actions/runs/37740115916): `Test (pwsh)`、`Test (powershell)`ともsuccess。
- [Autoupdate validation run 37740115767](https://github.com/takano536/scoop-bucket/actions/runs/37740115767): `validate`がsuccess。

現時点の`main`はstable channelのみを含む。開発channelは別PRのままmainへ未マージのため、この文書ではその機能や挙動を検証済みとは扱わない。

## ライセンス通知・名称/ロゴの公開条件（PR #6）

PR #6 の配布物は、対象commitの上流 `LICENSE` をそのまま `LICENSE` としてコピーし、
`THIRD-PARTY-NOTICES.txt` に実際に同梱された第三者コードの完全なlicense本文・
package固有の権利表示を収録する。Electron/Chromiumの既存
`LICENSE.electron.txt` と `LICENSES.chromium.html` も維持する。

通知対象は `win-unpacked` の実体を基準にする。`resources/app.asar` のheaderから
bundleに残る `dist/node_modules` packageを読み取り、`resources/app.asar.unpacked`
と `resources` 配下の物理 `node_modules` も走査する。さらに管理対象のbuild stepが
renderer Viteのsource mapとmain/preload esbuildのmetafileを出力し、そのsource path
からbundleへinline化されたpackageを解決してunionする。Vite emitterが記録した出荷CSS
source moduleの`url(...)`からpackage-owned assetも同じbundle graphへ追加する。
`devDependencies`はこのbundle graphで実際に参照されたものだけを含め、package.jsonに
列挙されただけの未出荷build-time toolingやproduction graph全体は通知対象にしない。
source map/metafile、CSS source、asset-origin manifestの取得や出力比較に失敗した場合は、
ライセンス違反とは分離した「追加監査のツール限界」としてprovenanceへ記録する。

このgraphは上流checkoutの変更を成果物へ持ち込むためのものではない。管理対象の
PowerShell build stepは、本番electron-builderが生成した上流の永続出力
`apps/desktop/dist`を、`scripts/build/desktop.mjs`のrenderer/main/preload成果物（`productOutput`
後にbuilderがpackした同じディレクトリ）として読み取る。同じstepで管理対象Vite/esbuild実行
からsource map/metafileとCSS source manifestを`apps/desktop/.hermes-bundle-graph`へ保存し、
graphの入力を作る。
asset-origin manifestはCSS、font、image、wasm、worker等のVite出力ごとに
originating source pathを記録する。notice stepは`app.asar/dist`と
`app.asar.unpacked/dist`の全ファイル（JS/CSS/assetを含む）を列挙し、JSはsource
map/metafile、その他はasset-origin manifestまたは`apps/desktop/src`/`public`/
`electron`等の明示的app-owned sourceを優先してpackage/app-owned originを解決する。
source mapの欠落・chunkの非対応、distとASAR/unpackedの出力比較差は、まず
`auditLimitations`として記録する。宣言されたproduction dependencies、lockfile、
build config、上流source、既存noticeで対象package/versionが解決できた場合は、この
fallback evidenceで監査対象を決定し、limitationsだけではpublishを拒否しない。
いずれの証拠でも個別の第三者出荷物を解決できない場合だけ、そのpath/packageを
`unresolved`へ列挙し、配布処理を拒否する。`dist/node_modules`はASAR/unpackedの
物理package scanで引き続き被覆する。
collectorはgraph/ASAR/unpackedが列挙したpackage自身だけを解決し、package.jsonの依存を推移走査して
未出荷packageを追加しない。配布条件の不足（license本文、copyright、NOTICE/source-offer）は
license validation failureとして、ツール限界は別の`auditLimitations`として記録する。

`LICENSE`/`LICENSE-*`/`LICENCE`/`COPYING` の完全な本文を特定できないpackageは
buildを失敗させる。package自身が同梱した完全なlicense本文はpackage固有copyright
行がなくても改変せず収録するが、`<copyright holders>`/`[year] [fullname]`などの
placeholderは拒否する。bucketで再構成するMIT本文には固定sourceのcopyright evidence
を要求する。`NOTICE`だけをlicense本文として扱わず、MPL本文の抜粋、未知/欠落license、
汎用SPDX template fallbackも成功扱いにしない。license検査は依存走査の最後まで続け、
失敗した全packageを一つのerror listに集約する。例外は
`scripts/hermes-desktop-light-license-overrides.json` のexact name/versionに
レビュー済み登録されたものだけで、package宣言とSPDXの一致、固定40文字commit URL、
取得元、license file/sourceのSHA256、copyright line（再構成時）を検証する。未使用
override entryはfailureにはせず、対象commitで未使用だったkeyとしてprovenance/notice metadataへ記録する。

MPL-2.0の実行形式を配布する場合は、通知にSource Code Formの取得方法を明記する。
noVNCについては、inventory graphが実際の実行形式の位置を分類し、同梱npm tarballと
対応upstream commitを固定URLで示す。bundleへinline/minifyされた場合と、未変更の
`node_modules` fileが出荷された場合を通知で区別する。`UNOFFICIAL-BUILD.txt`には
上流ref/commit、bucket commit、workflow URL、各licenseファイルの場所を記録し、
`provenance.json`にはbundle graph・通知ファイルのSHA256と対象package数を記録する。

`@audiowave/react@0.6.2` はnpm tarballにlicense fileがなく、tag
`@audiowave/react@0.6.2`である固定commit
`677823284c7fc9f0baf9e62a6d912192a7eb15f9`の`packages/react/package.json`が
version `0.6.2`であることを確認した。このcommitにはroot/`packages/react` LICENSEが
ないため、同commitのroot README（SHA256
`b131e67bff8cde4879eb0ba4595ab70cb99a0fcd6b9a76f06dc71f230cf0c87d`）を固定した
reviewed attribution evidenceを確認した。同じcommitの`packages/core/package.json`は
version `0.3.1`で同じroot attribution evidenceを確認した。今回の実CI inventoryでは
両packageのbundle moduleが検出されなかったため、未使用overrideを成果物へ残さず、
実際に出荷された版で再検出された場合だけこのexact evidenceを適用する。`khroma@2.1.0`は
package.jsonのlicense宣言がないが、exact npm tarballの`package/license`に完全な
MIT本文とcopyrightがあるため、そのtarball integrity/SHA256・file path・file SHA256
を固定したoverrideで補う。同一versionの証拠が得られないpackageはoverrideを追加せず
hard blockerとする。

### CIで追加検出したpackage evidence

Hermes Desktop Lightの最終実CI（run `37771200718`、head `eb7c4f104e6861f3e3ad2832e3f41c7a8acb7c6f`）では、実際の`win-unpacked` inventoryから`dbus-native@0.15.2`を`origin=bundle-map`として検出した。exact npm tarball
(`https://registry.npmjs.org/dbus-native/-/dbus-native-0.15.2.tgz`,
SHA256 `930b119209c999c992b9a7e7ac89fc5d62dbc035b8528e934ce18bb30f2b8da9`)自体に
`package/LICENSE`（SHA256
`435a6722c786b0a56fbe7387028f1d9d3f3a2d0fb615bb8fee118727c3f59b7b`）があり、
完全なMIT条項だがholder行はない。generatorはこのpackage-supplied本文を改変せず収録し、
holder行がないことを明記する。registry `gitHead`
`2126c95fd460c81d7b90e45a4588efdb23ba3f99`のupstream LICENSE（同一SHA256）でも
一致を確認した。bucket側のcopyright行追加やoverrideによる再構成は行わない。

同じ最終inventoryで`dijkstrajs@1.0.3`も`origin=bundle-map`だった。exact npm tarball
（`https://registry.npmjs.org/dijkstrajs/-/dijkstrajs-1.0.3.tgz`, SHA256
`07149886ab98299c227b8de61912770b24b8a17b250996a4b5727c9f8bff4c00`）の
`package/LICENSE.md`（SHA256
`c46324e45a005413535a6fb7a97e9eacd3cc6bf30335b7d5c10b8ee3af9e60c2`）がcopyright、
MIT license名、完全なdisclaimerを含む短縮形だった。registry `gitHead`
`49ad1ecd5c519281ee3c4711bb78db4d96e19c83`とも照合した。このpackage-supplied形式だけを
受理し、generic本文は引き続き拒否する。

一方、`@pkgjs/parseargs@0.11.0`は最終inventoryに存在せず（最終CIのorigin診断でも
`not-in-inventory`）、過剰なtransitive traversalを使っていた旧検出でのみ対象になった
非出荷transitive dependencyである。したがって現在のlicense gateの対象・hard blockerでは
ない。package.jsonがMIT宣言なのにexact tarball/upstream固定commitの`LICENSE`がApache-2.0
本文だったという宣言と実体の衝突は調査上の観察として残すが、未出荷packageの通知には追加しない。

最終確認run `37782539150`（head `126ff5c9e310d6311022c382f7dc9157d79d2195`）では、
inventory source countsは`asar=2`、`unpacked=2`、`bundle-map=352`だった。`@novnc/novnc@1.7.0`
は`bundle-map`のみで、未変更の`node_modules` fileではなくrenderer bundleへinline/minifyされた
実行形式であるため、通知にはMPL-2.0全文、packageの複数license notice、および「Source Code
Formは固定したnpm tarballとupstream commitから取得できる」という具体的な§3.2 pointerを入れる。
`@nous-research/ui@0.18.2`は出荷CSSの`url(...)`から参照されるfont assetとして
**履歴（remediation前）:** 旧runでのfailureは`@nous-research/ui@0.18.2`、
`lazy-val@1.0.5`、`react-remove-scroll-bar@2.3.8`、`unicode-animations@1.0.3`、
`use-composed-ref@1.4.0`（いずれも`origin=bundle-map`、当時は宣言MITに対応する
完全なlicense本文のexact-version evidenceなし）であり、当時はfail-closedだった。
現在のexact tarball/source evidenceと限定overrideは下記に記録する。

### 履歴：remediation前のWindows出力のfont/image/native確認（run 37801029051）

この節はnotice remediation前の履歴であり、現在の状態を表さない。出力一覧と
signing有無を測定していない出荷候補ファイルを確認したrun `37801029051`（上流
`a3ed4a173070e981332e4d879ff6cc8b9efd57ab`、head
`9af0940a8c287a63de6f7e24dc458b64def768bb`）の記録である。当時の最終ZIPはgate停止で
生成されず、以下は`win-unpacked`へpackされる対象と旧通知生成の5件failureの記録である。
JetBrains Monoは後続の固定hash/immutable OFL evidenceで解決された。その後のPR #6 head
run `37940526337`ではGitHub-hosted Windows runner上で最終ZIP・provenance・noticeを再確認
したが、`runnerIsClean=false`であり、一般のclean Windows環境を保証しない。

- **Font**: `Collapse-Bold-*.woff2` はCSSのsource pathが
  `@nous-research/ui@0.18.2`を指す。宣言MITだがexact tarballに完全本文/copyright
  evidenceがなく、5件のnpm不足に含まれる。`KaTeX_*`（Main/AMS/Math/Size/
  Caligraphic/Fraktur/Script/SansSerif/Typewriter、woff/woff2/ttf）は
  `katex@0.16.47`のpackage-supplied MIT本文を通知へ収録する対象で、generatorの
  package noticeに含まれる。`codicon-D*.ttf` は`@vscode/codicons@0.0.45`
  のCC-BY-4.0 package notice/attribution（同packageのlicense text）を収録する。
  `JetBrainsMono-{Regular,Bold,Italic}.woff2` は上流
  `apps/desktop/src/fonts`のapp-owned copied fontである。CSSのApache-2.0
  commentはfont name tableのOFL-1.1 metadataと一致しないため、license evidenceには
 使わない。後述のv2.305 blob hashとimmutable `OFL.txt`を照合し、異なるbytesは
  fail-closedするexact asset attributionへ置き換えた。
- **Image/icon**: `feature-{memory,automation,connect,sandbox}-*.webp`、
  `apps/desktop/assets`のicon/icon-dark（PNG/ICO/AppX各サイズ）、`apps/desktop/public`
  の`apple-touch-icon.png`/`nous-girl{,-dark}.png`等は対象commitのapp-owned source
  （`apps/desktop/src/assets`/`assets`/`public`）に対応する。第三者package由来の表示は
  asset graphでpackageとして扱い、上流root `LICENSE`のコピーと既存package noticeを
  適用する。別のcanonical third-party notice/source-offerはlogから確認できず、
  rights-holderの行は補っていない。
- **Auxiliary executable**: Electron自身（`electron.exe`）は既存
  `LICENSE.electron.txt`/`LICENSES.chromium.html`で被覆する。それ以外に出荷候補として
  `node-pty@1.1.0`の`winpty-agent.exe`、`conpty/OpenConsole.exe`（prebuildと
  build/Releaseの2経路）、上流`apps/desktop/electron/native`から生成する
  `native/win32-x64/hud-modifier-monitor.exe`がある。前二者はnode-pty package-supplied
  MIT notice、後者は対象commitの上流sourceとroot Hermes MIT `LICENSE`を根拠とする。
  logにはこれ以外の出荷`.dll`はなかった。stagingされた`get-windows@9.3.0`のJS packageは
  package-supplied MIT noticeの対象（単独native binaryなし）、build環境の
  `pywinpty==3.0.5`は出力へpackされないbuild-only dependencyとして分離する。
  （履歴）gate停止時点では最終ZIP内のnotice同梱をWindows acceptanceで再確認できなかった。その後の
  run `37940526337`ではGitHub-hosted Windows runner上で最終ZIP/provenance/noticeを再確認したが、
  `runnerIsClean=false`であり、cleanな一般Windows環境のruntime独立性は保証しない。

上記のうち完全本文/evidenceが確認できないものは配布条件不足として扱い、tool limitationや
権利者の義務免除とは表現しない。

名称・ロゴについては、対象commitのREADME、desktop identity、electron-builder設定、
Contributing、公式サイトに明記された制限だけを根拠にする。明記がない条件を
「許可」とは扱わず、個別の許諾が必要だとも断定しない。第三者再配布での商標・
ロゴ利用規則が上流資料から確認できない場合は、`UNOFFICIAL-BUILD.txt` の表示だけで
解消したとは扱わず、公開前の未確認事項として残す。

### Official distribution notice survey and exact asset/package evidence

The read-only official distribution survey completed in
[Actions run 37936205871](https://github.com/takano536/scoop-bucket/actions/runs/37936205871).
Its `official-notice-survey` artifact is
[artifact 11617734477](https://api.github.com/repos/takano536/scoop-bucket/actions/artifacts/11617734477),
with digest `sha256:a8cf344ad4bab06ec15e5dc67d36199b24072da2c1b82bade866643e8d125ce6`
and compressed size 6,925,588 bytes. The fixed canary bundle
`HermesBundled-26.1008.7.449-win.msixbundle` was SHA256
`9b05aae0ac776becf30840297583dfaca841da7855acc22c58352df39f33a517`; the feed's
current `HermesBundled-26.1009.7.410-win.msixbundle` was SHA256
`5b1ccae5cf64fb1ad5917bf54f801f9a88ffd45e936b3d8212eaea5071ab3e98`.
The fixed/current x64 MSIX SHA256 values were
`db459b3ccf0bbfab9c2255bd083b8a7425f01d4fd8e2ee73d92162e4a58c4c1b` and
`86f9b73fd5c2fab29525d3391e176c80169ed1cda999eafa5f17baebc5c1cdad`.

The official MSIX inventory contains Hermes Agent's own `LICENSE` and plugin/skill
`LICENSE`/`NOTICE` files, but no canonical third-party notice for the five npm
packages below. Official distribution therefore is not used as compliance evidence
for those packages. Its install stamps identify canary commits
`a28a5d03a9fa60418db5f44f3436fa2aa029c8f2` (fixed) and
`1744a19e0df568c647e4f3ff9c37f2a284a282fb` (current), not the Light pins
`a3ed4a1`/`38880bd`.

JetBrains Mono is resolved by bytes, not the upstream CSS comment. The shipped
Regular/Bold/Italic WOFF2 hashes are respectively
`f1a7a03672cdd494ce0d5543fac6e4360fe22403c6de297fdc2e55a815f7baff`,
`08863c7964612257a90bd821e3127dc5ccb0b5046f881673a1ade5809eb21d0f`, and
`9f158b85eca345daeee01dfffa602709a905ea08b0cc60dbf6153cbbd97da08f`.
Font name tables identify version 2.305, copyright
`Copyright 2020 The JetBrains Mono Project Authors (https://github.com/JetBrains/JetBrainsMono)`,
and SIL Open Font License 1.1. Each hash is matched against its immutable source
at commit `19371302b95d218af43299bce79ddbddd0bc364d`; the complete
[OFL.txt](https://raw.githubusercontent.com/JetBrains/JetBrainsMono/19371302b95d218af43299bce79ddbddd0bc364d/OFL.txt)
is fetched with SHA256
`a76abf002c49097d146e86740a3105a5d00450b1592e820a1109a8c5680cd697`.
The upstream CSS's Apache-2.0 comment is inconsistent with the embedded font
metadata and is not used. A filename match with different bytes remains a
fail-closed blocker.

The exact package overrides record registry tarball URL, integrity, SHA256,
package metadata, and absence of license/copyright-named members. They never
synthesize a copyright line:

- `@nous-research/ui@0.18.2`: declared-only MIT evidence; no author field,
  no license/notice member, and no available source repository license.
- `lazy-val@1.0.5`: declared-only MIT evidence; verbatim author metadata is
  `Vladimir Krivosheev`, but the exact source tree has no license file.
- `react-remove-scroll-bar@2.3.8`: complete MIT license from author-added
  immutable commit `7301c160fda44cb8cf2b9fdfde61efad35736196`
  (SHA256 `a79aae0c0f21990d9d963bb3c5a79cdcea9a46f8523ba55c58d7fe776b6ebc84`).
  The npm `gitHead` is unavailable and this license commit is later than the
  published package, so the evidence is explicitly recorded as later
  project-level evidence rather than exact source-tree identity.
- `unicode-animations@1.0.3`: declared-only MIT evidence; no author field,
  no license/notice member, and no license file in the exact or nearby source.
- `use-composed-ref@1.4.0`: declared-only MIT evidence; no author field,
  no license/notice member, and no license file in the exact tag/source tree.

Declared-only output records the SPDX declaration and verbatim package.json author metadata
when present. No license text or copyright notice was obtained from these four packages, so
these remain declared-only records and no package-specific copyright line is synthesized.
Existing package/Electron/Chromium notices are preserved; any standard MIT text emitted for
the declared SPDX is generated boilerplate, not package-supplied evidence.
Any package outside these exact entries, a changed tarball, or a package that
starts shipping a notice file fails closed. The five package entries and the
font evidence still require the Windows Light workflow to exercise the actual
`win-unpacked` inventory.

### First-party Windows HUD helper attribution

The remaining notice-gate failure was the generated
`native/win32-x64/hud-modifier-monitor.exe`. At both Light pins (`a3ed4a1` and
`38880bd`) the upstream `apps/desktop/scripts/build-hud-modifier-monitor.mjs:1-24,41-76`
compiles the in-repository
`apps/desktop/electron/native/hud-modifier-monitor-win.cs` and
`hud-modifier-gesture.cs` with the Windows .NET Framework `csc.exe`; it does not
download or copy a prebuilt helper. The source only uses the Windows
`System.Windows.Forms`/`user32.dll` APIs, with no Rust crate or third-party C
library linked into this Windows binary. `stage-native-deps.mjs:735-745` invokes
that compiler, while `before-pack.mjs:136-143` copies the prepared output.

The build log for the failed verification run
[`37938735244`](https://github.com/takano536/scoop-bucket/actions/runs/37938735244)
records the native preparation and `built ...hud-modifier-monitor.exe` before electron-builder
packaging. Any log wording about signing is not an Authenticode check of the shipped EXEs:
the build and acceptance evidence contains no `Get-AuthenticodeSignature`, `signtool`,
certificate, or signature-result measurement. The notice generator now records this exact
output under `firstPartyAssets`, lists its verified upstream source paths, and attributes it to
the checked-out upstream root `LICENSE` (MIT). The mapping is exact; an unknown native
executable, or a missing source/build path, remains fail-closed.

## Development channelの公開・transition

development Releaseは`hermes-desktop-light/dev/v<version>-<full SHA>` tag、
`prerelease=true`、`latest=false`で公開し、同じupstream commit・conditions fingerprintの
Release/assetを上書きしない。公開前にWindows acceptanceの`acceptance.json`をbuild provenance
と突合し、public URLのSHA256を再取得してからmanifest・READMEを書き戻す。

stable Releaseが存在するだけではdevelopmentを停止しない。stableのtag/claim admission、
build、Windows acceptance、Release公開、manifestのRelease URL/SHA256 readbackがすべて確認され、
`metadata/hermes-desktop-light-channel.json`へ記録された場合だけ、次回planがdevelopmentを
hard-refuseする。stable buildのfailure/skipではdevelopmentを継続する。

## 未確認事項と配布開始条件

今回のrunはPR用previewであり、次は未確認である。

次の受入結果はPR #8時点の履歴である。Light ZIPに`resources/agent-payload`がなく、
restricted PATH下のlocal backend probeが`bootstrap-needed`を返し、bootstrap/local agentを
起動しないこと、同一upstream commitのgatewayへの認証、誤secret拒否、Scoop update後の
接続設定保持を確認した。ただしrunnerはクリーンなWindowsではなく、安定版の実アップグレード
や配布を証明しない。現行development run 37779700289はlicense gateでacceptance未実行である。
- 対応安定版でのtag/claim admission、安定版の実ビルド、安定版のScoop version。
- 異なるバイナリ間の実migration。今回確認したのは同じpreview ZIPのtest-only version bumpだけである。
- GitHub Releases公開、manifest/READMEのmain書き戻し、安定版の実アップグレード。
- クリーンなWindows consumer machineでのruntime独立性。
- provider/LLM credentialを使う実運用。

初回manifestは、Light対応の安定版を実際にビルド・受入確認・公開できた後に生成する。main由来のコードを過去安定版の名前で配布しない。公開ゲート`HERMES_DESKTOP_LIGHT_RELEASE_ENABLED`は有効化せず、PRからReleasesへ公開しない。

## 公開ゲート

### Development公開ゲートと自動化の追加検証

development公開は`HERMES_DESKTOP_LIGHT_DEV_RELEASE_ENABLED`、stable公開は
`HERMES_DESKTOP_LIGHT_RELEASE_ENABLED`が`true`の場合だけ実行する。両変数は未設定で、
今回の作業では有効化しない。対応stableが出ても、stableのtag/claim admission、build、
Windows acceptance、Release公開、公開URL/SHA256照合、manifest readbackが終わるまで
developmentを停止しない。stable buildのfailure/skipだけではtransitionしない。
検出・read-only buildは公開gateと分離する。

publisher自身もActionsのschedule/workflow_dispatchかつmainとchannel固有gateを要求する。
ローカル開発checkoutやPRで誤って実行しても、API操作やhard resetの前に停止する。
成果物取得に必要な`actions: read`を公開jobへ明示する。publishは同じrunのbuild・Windows
acceptanceを要求し、`acceptance.json`のpassed status、source commit/version、ZIP名/SHA256、
license/notice provenanceを突合する。公開済みassetは上書きしない。

`GITHUB_TOKEN`によるpush後の検証は、Desktop Light成功後の`workflow_run`でScoop標準CIと
Autoupdate validationを起動する。元runが同一リポジトリのmainで成功した場合だけread-onlyで
書き戻し済みの正確な40桁SHAをcheckoutし、元runの成果物は実行しない。README生成・検証は
publisher内で完了させる。このmain連携の実運転はマージ前には未検証である。

公開処理の回帰テストは、合成ZIP・mock GitHub API・使い捨ての実Gitリポジトリを使う。
初回Draft作成から公開URL照合後のmanifest/README更新、公開済みアセットの再利用と
冪等再実行、異なる部分Draftの拒否、タグ移動、ハッシュ不一致、downgrade、push失敗、
README書き戻しのreadback不一致、公開ゲートを検証する。本番公開の証明ではない。

Windows smokeには、ビルド用Python/Node/Gitを含まないPATHでの起動と、実preloadからの
updater check/applyを追加した。結果は `native-checks.json` と `provenance.json` に残す。
これは初期起動とexternal updaterの確認であり、リモートgateway接続、PATH以外の
インストール済みランタイムからの独立性、安定版の実アップグレードを保証しない。
実CI結果はPRに記録する。

### Development channelの配布契約の検証記録

対象PR #10 head `b99383e8ed48f4301bf8542a6ba651692de337e1`について、次の検証を記録する。

| 検証 | 結果 |
| --- | --- |
| Python回帰テスト | 74件成功。Hermesのexact commit/Light contract、conditions fingerprint、revision no-op、license/notice admission、publish/acceptance gateを含む |
| ローカル静的検証 | README生成チェック、Node構文、git diff --check、legacy-name guard成功 |
| [CI](https://github.com/takano536/scoop-bucket/actions/runs/37779700306) | 成功。Windows PowerShell / PowerShell 7、Scoop Compare-Versionのpin検証を含む |
| [Autoupdate](https://github.com/takano536/scoop-bucket/actions/runs/37779700250) | 成功 |
| [README](https://github.com/takano536/scoop-bucket/actions/runs/37779700251) | 成功 |
| [Hermes Desktop Light](https://github.com/takano536/scoop-bucket/actions/runs/37779700289) | plan成功。上流`25a71a744cb9ef06950a91638e6229b4f808d461`を解決したが、buildは4 packageのlicense gateで失敗し、acceptance/publishはskip |

### 成果物と上流commit

- planが解決した上流commit: `NousResearch/hermes-agent@25a71a744cb9ef06950a91638e6229b4f808d461`。
- version: `0.0.0-alpha.dev.1-r1`。条件fingerprint: `9223aa09872794c9b7ceac52d7c871c0fbbfaeaceddad19a1ce20908f3801309`。
- license gateでbuildが完了しなかったため、公開ZIP、acceptance artifact、Release、manifest/README書き戻しはない。
- license gateの未解決packageは`lazy-val@1.0.5`、`react-remove-scroll-bar@2.3.8`、
  `unicode-animations@1.0.3`、`use-composed-ref@1.4.0`である。

これは固定commitのpreviewであり、対応安定版の更新所有・gateway接続・認証移行の
証明ではない。対象安定版、ライセンス通知の同梱、実gateway接続、実更新時の設定保持、
過去版のScoop導入/固定は未確認である。公開実運転はマージと明示的承認後にのみ確認
可能で、公開ゲート未設定、マージ・実Release作成なし。
差分レビューはHermes自身で実施、独立モデルレビューは未実施。
### Stable公開ゲート

公開jobは`HERMES_DESKTOP_LIGHT_RELEASE_ENABLED`が`true`、scheduleまたは`workflow_dispatch`、`main`、build対象のすべてを満たす場合だけ実行する。公開前に、対象tagと同梱物のライセンス・著作権表示・第三者通知、名称と非公式配布表示、Windows実行・必要runtime・更新移行・外部サービス接続を再検証する。公開済みassetを上書きせず、manifest・READMEは公開URLからSHA256を再検証した後に書き戻す。

## 配布契約の検証記録

（履歴）この段落は公開前のpreviewに対する記録であり、現在の公開状態は末尾の
「現在のdevelopment公開とpublic Scoop install」を参照する。Actions artifactは一時検証用であり、
Scoopの恒久的な配布先ではない。

## 現在のdevelopment公開とpublic Scoop install（2026-10-10）

上記の初期preview／公開前の記録（特に「Release・manifest登録・main書き戻しはない」と
記した箇所）は履歴である。以下が、初回の非公式development公開と、公開bucketからの
実Windows導入についての現在の検証記録である。

- Release: [`Hermes Desktop Light development release`](https://github.com/takano536/scoop-bucket/releases/tag/hermes-desktop-light%2Fdev%2Fv0.0.0-alpha.dev.1-r1-46d7718a52ff33accb15dc0501736fbdb6833cab)。
  `draft=false`、`prerelease=true`、名前と本文は `DEVELOPMENT BUILD — NOT STABLE` /
  `Unofficial unsigned Windows x64 Light build` である。
- publish run: [38008376760](https://github.com/takano536/scoop-bucket/actions/runs/38008376760)。
  upstreamは`NousResearch/hermes-agent@46d7718a52ff33accb15dc0501736fbdb6833cab`、
  buildのbucket headは`11b4ead`、書き戻しcommitは
  [`d6efc008`](https://github.com/takano536/scoop-bucket/commit/d6efc008b37bdfe30204cf6fa0e30b196b559616)である。
  versionは`0.0.0-alpha.dev.1-r1`、公開ZIP SHA256は
  `c83d413c6599827a82cf881bb90bdf7e395056ae36f3e79e6b2b4b59a71f3c23`である。
- manifest・READMEは公開URLとSHA256をread backしてmainへ書き戻した。現在のdevelopment
  planを同じupstream commit、revision `1`でread-only評価すると、既存Release/asset/
  conditionsを認識して`build=false`のno-opになる。upstream `main`が進んだ場合は、
  4時間ごとのscheduleが新しいdevelopment buildを作る（gateはdevelopmentだけ有効である）。

- [Autoupdate validation run 38009253446](https://github.com/takano536/scoop-bucket/actions/runs/38009253446)で、
  checkverが`0.0.0-alpha.dev.1-r1`を検出し、development pointerのURL/SHA256を
  再生成・照合して成功した。

### 公開bucketからの実Windows検証

[Scoop install workflow run 38013077481](https://github.com/takano536/scoop-bucket/actions/runs/38013077481)
はGitHub-hosted `windows-latest`上で、secretなし・`contents: read`だけのworkflowとして
公開bucketをalias `takano536-verify`で追加し、`scoop install`、`scoop list`、`scoop info`、
既存のElectron acceptance driverを実行した。

- public manifestのversionは`0.0.0-alpha.dev.1-r1`、download URLは上記Release asset、
  SHA256は`c83d...f3c23`で一致した。Scoop cacheの実ダウンロードも同じSHA256で、
  hash verificationは成功した。
- `scoop prefix`は`...\\apps\\hermes-desktop-light\\0.0.0-alpha.dev.1-r1`、
  `current` junctionも同versionを指した。manifestの`shortcuts[0][0]`から7桁hex suffix
  `46d7718.exe`の実行ファイルを読み取り、その実在とStart-menuの
  `Hermes Desktop Light (Development).lnk`のtargetを確認した。
- インストール後の起動はCDP renderer readiness、gatewayへの正しいsecret接続、
  誤secret拒否、`/api/sessions`のauthenticated 200／誤secret 401、remote設定保持、
  local backendの`bootstrap-needed`、developmentのexternal updater
  `commit-build`（check/applyはunsupported/refused、app tree不変）を既存acceptance
  driverで確認した。
- Authenticodeは同runで`Get-AuthenticodeSignature`を20個の`.exe`/`.dll`/`.node`へ実行した。
  the manifest-derived main `.exe` (7-hex suffix `46d7718`) and HUD helper, plus 12 other
  files, were `NotSigned`.
  一方、次の6ファイルは`Valid`で、signerはすべて
  `CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US`だった：
  `d3dcompiler_47.dll`、`dxil.dll`、`node-pty`のbuild/release `conpty.dll`・
  `OpenConsole.exe`、およびprebuild側の`conpty.dll`・`OpenConsole.exe`。
  したがって`unsigned`は本プロダクト／main exeのbuild labelであり、ZIP内の全依存
  binaryが未署名という意味ではない。署名状態はcleanな一般Windowsの保証ではない。
- このrunのrunnerはGitHub-hostedであり、**cleanな一般Windows環境を保証しない**。Releaseは
  Nous Researchと提携していない非公式development buildであり、stable gateは有効化していない。
  `HERMES_DESKTOP_LIGHT_DEV_RELEASE_ENABLED=true`のままのscheduleは、upstream変更時に
  新しいdevelopment版を公開し得る。provider credentialを使う実運用、stable upgrade、
  異なるbinary間のmigration、およびclean consumer machineでの独立性は未確認である。
