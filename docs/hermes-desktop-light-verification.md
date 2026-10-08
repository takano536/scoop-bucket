# Hermes Desktop Light 検証
共通の[配布ルール](distribution-policy.md)と[検証記録](distribution-validation.md)を前提に、
Hermes Desktop Light固有の上流・Light・gateway契約と実行結果をこの文書へ記録する。

## Hermes Desktop Light固有の上流・実行契約

- 対象の安定タグは、上流の`STABLE_TAG_RE`と同じ`vX.Y.Z`形式のSemVerだけとする。
  Draft・Prerelease・canary・`v2026.9.24`のような歴史的CalVerは対象外である。
- 上流のstable-release toolingが先に作る`rc.N-vX.Y.Z` annotated claimと、公開時の
  `vX.Y.Z` annotated tag本文に入る`claimTag`・`claimTagObject`付きJSON receiptを
  検証する。Release状態、タグから解決したcommit、claimのversion/commit/
  `claimTag`/`claimTagObject`が一致しないtagはadmissionしない。
- sourceのLight identityと管理されたLight builderの対応ファイルを検査し、非対応や
  必要ファイルのないcommitは理由を記録してskipする。API障害や権限エラーはskipと
  混同せず失敗させる。
- この配布物はリモート専用のLight構成で、既存のHermes gatewayへの接続を必要とする。
  起動smokeだけではgateway接続、認証・接続設定の移行、Lightのローカル実行可否を
  証明しない。これらはWindowsで別途受入確認する。

## 個別検証の入口

共通のローカル手順は[検証手順](verification.md)から実行する。Hermes Desktop Light固有の
Node.js smokeスクリプトは、次で構文を確認する。

```bash
node --check scripts/smoke-hermes-desktop-light.cjs
```

PythonのHermes Desktop Light・配布契約テストは、共通の`unittest discover`に加えて、必要なら
次のように個別実行できる。

```bash
python3 -m unittest discover -s tests -p 'test_hermes_desktop_light*.py' -v
python3 -m unittest discover -s tests -p 'test_distribution.py' -v
```

## Hermes Desktop Light workflow

[`hermes-desktop-light.yml`](../.github/workflows/hermes-desktop-light.yml)は、UTCの4時間ごとのschedule、
`workflow_dispatch`（`revision`入力）、および関連ファイルを変更したPull Requestで
起動する。`plan`はUbuntuで個別テストと`hermes-desktop-light.py plan`をread-only実行し、
Light対応と対象を決める。対象がある場合だけ`build`がWindows 2025でビルド・smokeを
実行し、`hermes-desktop-light-windows-x64` artifact（保持14日）を作る。

`publish`は`vars.HERMES_DESKTOP_LIGHT_RELEASE_ENABLED == 'true'`、scheduleまたは
`workflow_dispatch`、`refs/heads/main`、build対象のすべてを満たす場合だけ実行する。
公開済みassetの再検証とRelease公開、manifest・READMEのmain書き戻しを行うpublishの
詳細なゲートと未確認事項は、この文書の公開ゲート節に従う。Pull Requestではpublishを
実行しない。

## Hermes Desktop Lightの改訂

通常の安定版追従は`r1`。公開済みの同じ上流版を修正する場合、信頼済みmainの手動workflowの`revision`に`2`などを指定する。
対象はその時点の最新対応安定版。過去上流版を指定してのバックポートビルドは現在の自動化の対象外。
改訂番号は正の整数で、先頭ゼロを許可しない。既存manifest以上の版がなければskipし、定期実行が`r2`を`r1`へ戻すことはない。
番号は承認済み修正のために管理者が指定するもので、CI再実行数から自動採番しない。公開ゲート`HERMES_DESKTOP_LIGHT_RELEASE_ENABLED`は引き続き既定で無効。
Hermes Desktop Lightのgateway接続・認証移行などの既存阻害条件は、この改訂ルールで解消したとは扱わない。

## 実Windows CI

- [ビルド・起動検証](https://github.com/takano536/scoop-bucket/actions/runs/37620186448)
- 上流: `NousResearch/hermes-agent@a3ed4a173070e981332e4d879ff6cc8b9efd57ab`
- 検証ZIP: `hermes-desktop-light-preview-a3ed4a1-windows-x64.zip`
- SHA256: `b83ff46eaed9e30600f7dafcb2ed69c0521bb50ff7dc925e6b5362110d325ec9`
- ZIP: 170,392,861 bytes / 1,191 entries。ダウンロード後のSHA256照合とZIP CRC検証に成功。
- Packaged Electronの起動・再起動とlocalStorage保持を検証。`payload=light`、
  `updateMechanism=external`、source commit一致、`resources/agent-payload` 非同梱を確認。
- 設定先にはCIの一時ディレクトリを使用。実gatewayや認証情報を与えていない。
- これはPR専用の検証成果物。安定版としての公開・manifest登録はしていない。

![Windows CIでの初回起動画面](images/unformatted/hermes-desktop-light-preview.png)

画像はScoop標準のテキスト整形テストの対象外である `unformatted` 領域に置く。

## 成果物の保存先とskip条件

- 対象ソースのLight identityと管理されたbuilderを検査し、非対応・必要ファイルなしは
  正常なskipとする。API障害・権限エラーは非対応と混同せず失敗させる。
- PRはLight対応を確認した固定commitのpreviewビルド。安定版の検出とは独立している。
- Windows runner上では `upstream/apps/desktop/release/win-unpacked` を直接ZIP化し、
  `output/` にZIP・provenance・smoke証拠を置く。ここでの `release/` は上流の
  ローカルビルド出力ディレクトリであり、GitHub Releasesへの公開ではない。
- CIからの保存先はActions Artifactsの `hermes-desktop-light-windows-x64`（保持14日）。
  リポジトリへバイナリをcommitせず、PRからReleasesへも公開しない。
- 将来のScoop配布用GitHub Releases公開は、mainかつ明示有効化されたpublisherのみ。
  現在は無効のままで、マージや公開の有効化は今回の作業に含めない。

## Windows受入ジョブ

`.github/workflows/hermes-desktop-light.yml` の`acceptance` jobは、`build`の
Actions ArtifactをWindows runnerへ渡し、実行時だけ作るdisposable local bucketの
test-only manifestで次を確認する。manifestはbucketの本番ツリーには追加しない。

`New-ScoopUpdateSummary` はassertionを実測したbefore/after version、resolved current
target、shortcut target（resolved target）と突き合わせ、各値が空でなく一致し、
before/afterがno-opでなく、afterが期待version・current target・shortcut target
（`expectedVersion`・`expectedCurrentTarget`・`expectedShortcutTarget`）に一致する
場合だけsummaryを生成する。このsummaryが`scoop-update-evidence.json`の`summary`と
`acceptance.json`の`scoop`に書き込まれる。

- Scoop install前後の`current/manifest.json`とScoopのinstall receipt（環境によっては
  receiptが作られないため`Scoop list`の実測行）を読み戻し、`version`一致を確認する。
  before/afterは`0.0.0-test-before-<commit>`と
  `0.0.1-test-after-<commit>`という異なるtest-only versionであり、同じ版のno-op更新は
  assertionの回帰テストを含めて失敗する。
- before/afterのresolved `current` targetとStart Menu `.lnk` targetを読み戻し、
  after versionが期待版、resolved current targetが変更、shortcut targetがafterの
  installed executableを指すことを`Assert-ScoopUpdateSwitch`でassertする。実測値は
  `scoop-update-evidence.json`と`acceptance.json`へ記録する。
- Scoop install/update/uninstall、Start Menuの`.lnk`経由起動、アプリ本体と
  shortcutの削除、`HERMES_HOME`/Desktop user-dataの残存。
- インストール済みapp treeの全`*.dll`/`*.exe`/`*.node`を`dumpbin /DEPENDENTS`で
  列挙・parseし、各importをapp tree（importing module directoryを優先）または
  Windows 10+のKnownDLLs/System32へ解決する。`api-ms-win-*`/`ext-ms-win-*`
  API setは`LoadLibraryEx` probeでhostのApiSet schema解決を実測し、`ucrtbase.dll`
  はWindows 10+ OS提供コンポーネントとして扱う。
- `vcruntime140*.dll`、`msvcp140*.dll`、`concrt140.dll`、`vccorlib140.dll`、
  `mfc*`等のVC++ redistributable importがapp treeに同梱されない場合はacceptance
  failure（publish blocker）とし、unparseable PE・unresolved importも同様に扱う。
  診断だけで成功にせず、runtime evidenceには各file/import/resolution/API-set probeと
  failureを記録する。Electronの対応最小環境と同じWindows 10+を前提とする。
- GitHub-hosted Windows runnerはクリーンなWindowsではないため、runner上で解決・起動
  してもクリーン環境のruntime独立性を証明しない。この制限は受入条件として維持する。
- 上流checkoutと同じcommitの`hermes serve --skip-build`をlocalhostで起動し、
  job内で生成した`HERMES_DASHBOARD_SESSION_TOKEN`をmaskして、Desktopの実HTTP+
  WebSocket接続を確認する。接続設定はUIクリックではなく、CDPからアプリの
  preload bridge IPC（`applyConnectionConfig`、`getConnectionConfig`、
  `getGatewayWsUrl`）を呼ぶ。Scoop update後は、保存済みsecretからbridgeがmintした
  WS URLだけをrendererへ渡し、renderer自身が`session.list` JSON-RPCを送り、返却された
  `result.sessions`を検証する。別にNodeから`/api/sessions`を呼ぶ結果はdirect gateway
  probeと明示する。provider/LLM credentialは渡さない。
- `resources/agent-payload`なし、local backend probeが`bootstrap-needed`で
  bootstrapを実行しないこと、remote接続設定、Scoop更新後の設定・認証・
  authenticated round-trip保持、in-app updaterの`external`/unsupported拒否と
  app tree不変を確認する。

以下のrunはこの強化前の実装による履歴であり、新しい版切替assertionおよび全PE import受入の成功証拠として扱わない。最新runでは版切替と全PE検査を実行し、未同梱VC++ redistributableが見つかったため公開blockerとして失敗した。
最新の実Windows受入run: [37714650337](https://github.com/takano536/scoop-bucket/actions/runs/37714650337)。実測evidenceは`hermes-desktop-light-windows-acceptance` artifactへ保存した。

- run: [37673954715](https://github.com/takano536/scoop-bucket/actions/runs/37673954715)
- acceptance job: [112983466324](https://github.com/takano536/scoop-bucket/actions/runs/37673954715/job/112983466324)
- upstream: `NousResearch/hermes-agent@a3ed4a173070e981332e4d879ff6cc8b9efd57ab`
- このrunのbucket commit: `371b9a0`
- build ZIP: `hermes-desktop-light-preview-a3ed4a1-windows-x64.zip`
- ZIP SHA256: `72f30c28b60e43c31f344681a425818f8400a7515378e04ee7f09044783f7648`
- acceptance artifact: `hermes-desktop-light-windows-acceptance`（保持14日）
- Scoopのtest-only before/after version、Start Menu shortcut、uninstall後のapp/shortcut削除と
  user-data残存を確認。preload bridge IPCを通じたアプリ側の認証済み`session.list`
  WebSocket RPC、同一gatewayへのdirect Node `/api/sessions` probeの`200`、誤secretの
  `401`、Scoop update後の設定・tokenSet保持を確認。
- 異なるLight対応upstream commitの同一runビルドはまだないため、before/afterは
  同じZIPを異なるtest-only versionとして使った。これはScoop更新時の設定保持を
  検証するが、異なるバイナリ間のmigrationは証明しない。
- 旧runのPE調査では検査対象のruntime importsと同梱CRT DLLが空だった。ただしrunnerIsCleanは
  `false`であり、クリーンなWindowsへのruntime独立性は未証明。最新runではWindows 10+
  API-set probeを実施し、OS提供API set/UCRTとVC++ redistributableを区別して記録した。
- previewのin-app updaterは`mechanism=external`、`reason=commit-build`を返し、
  applyを拒否しapp tree不変だった。local-install表示は残るが、probeは
  `bootstrap-needed`で、ローカルagentの起動は行われなかった。
- pinned upstream protocol basis: `apps/desktop/electron/preload.ts:49-52,276-279`
  exposes the URL/config bridge IPC; `apps/desktop/electron/gateway-ws-probe.ts:4-13`
  documents the renderer `/api/ws` handshake; `apps/shared/src/json-rpc-channel.ts:12-18,248-325`
  defines JSON-RPC frames/requests; and
  `apps/shared/src/gateway-contract.openrpc.json:3394-3410,31168-31182`
  defines `session.list` and its `{sessions}` result.
- updater source is also pinned: `apps/desktop/electron/updater/external.ts:20-35`
  returns `reason=commit-build` only for `source=commit-build`, otherwise
  `reason=bundled-not-appinstaller`; its non-commit branch returns
  `{ok:true, manual:true, bundled:true, mechanism:'external'}`. This is
  source-grounded, but stable behavior remains unexecuted because no stable
  Light artifact exists.

受入artifactの`acceptance.json`、`before.json`、`after.json`、runtime evidenceと
gateway/httpログをrun artifactから取得できる。将来の別runでは、そのrunのURLと
SHA256を追記し、未実行のrunを検証済みとは扱わない。

## ライセンス通知・名称/ロゴの公開条件（PR #6）

PR #6 の配布物は、対象commitの上流 `LICENSE` をそのまま `LICENSE` としてコピーし、
`THIRD-PARTY-NOTICES.txt` に実際に同梱された第三者コードの完全なlicense本文・
package固有の権利表示を収録する。Electron/Chromiumの既存
`LICENSE.electron.txt` と `LICENSES.chromium.html` も維持する。

通知対象は `win-unpacked` の実体を基準にする。`resources/app.asar` のheaderから
bundleに残る `dist/node_modules` packageを読み取り、`resources/app.asar.unpacked`
と `resources` 配下の物理 `node_modules` も走査する。renderer/main bundleへ
インライン化されたpackageは、bundler metadataまたはproduction dependency graphで
同定できる場合に含め、desktop/workspaceの `devDependencies` や、artifactへ入らない
build-time toolingは含めない。物理inventoryまたはproduction graphにあるpackageを
解決できない場合はfail-closedとする。

`LICENSE`/`LICENSE-*`/`LICENCE`/`COPYING` の完全な本文とpackage固有の権利表示を
特定できないpackageはbuildを失敗させる。`NOTICE`だけをlicense本文として扱わず、
MPL本文の抜粋、package固有copyright行のないMIT、未知/欠落license、汎用SPDX
template fallbackも成功扱いにしない。license検査は依存走査の最後まで続け、
失敗した全packageを一つのerror listに集約する。例外は
`scripts/hermes-desktop-light-license-overrides.json` のexact name/versionに
レビュー済み登録されたものだけで、package宣言とSPDXの一致、固定40文字commit URL、
取得元、license fileのSHA256、copyright lineを検証する。未使用override entryも
失敗させる。

MPL-2.0の実行形式を配布する場合は、通知にSource Code Formの取得方法を明記する。
noVNCについては、同梱npm tarballと対応upstream commitを固定URLで示し、minifyを
含む実行形式に対応する未変更sourceの取得先を記録する。`UNOFFICIAL-BUILD.txt`
には上流ref/commit、bucket commit、workflow URL、各licenseファイルの場所を記録し、
`provenance.json`には通知ファイルのSHA256と対象package数を記録する。

`@audiowave/react@0.6.2` はnpm tarballにlicense fileがないため、固定upstream
README commitの取得元・SHA256・`Copyright (c) teomyth` を記録したowner-review
overrideのみを適用する。`khroma@2.1.0` はpackage.jsonのlicense宣言がないが、
exact npm tarballの `package/license` に完全なMIT本文とcopyrightがあるため、
そのtarball integrity/SHA256・file path・file SHA256を固定したoverrideで補う。
同一versionの証拠が得られないpackageはoverrideを追加せずhard blockerとする。

### CIで追加検出した未解消項目

Hermes Desktop Lightの実CI（run `37744831557`）では、実際の`win-unpacked` inventory
から次も検出された。`dbus-native@0.15.2` はexact npm tarball
(`https://registry.npmjs.org/dbus-native/-/dbus-native-0.15.2.tgz`,
SHA256 `930b119209c999c992b9a7e7ac89fc5d62dbc035b8528e934ce18bb30f2b8da9`)と、
registryの`gitHead` `2126c95fd460c81d7b90e45a4588efdb23ba3f99`に対応するupstream
`LICENSE`（固定URL
`https://raw.githubusercontent.com/sidorares/dbus-native/2126c95fd460c81d7b90e45a4588efdb23ba3f99/LICENSE`,
SHA256 `435a6722c786b0a56fbe7387028f1d9d3f3a2d0fb615bb8fee118727c3f59b7b`）を調査した。
本文はMITの完全な条項だがpackage固有のcopyright holder行がなく、README/treeにも
補足表示がないため、汎用行の追加や別versionの流用はせずfail-closedで残す。

名称・ロゴについては、対象commitのREADME、desktop identity、electron-builder設定、
Contributing、公式サイトに明記された制限だけを根拠にする。明記がない条件を
「許可」とは扱わず、個別の許諾が必要だとも断定しない。第三者再配布での商標・
ロゴ利用規則が上流資料から確認できない場合は、`UNOFFICIAL-BUILD.txt` の表示だけで
解消したとは扱わず、公開前の未確認事項として残す。

## 未確認事項と配布開始条件

最新の公開安定版 `v2026.9.24` にはLightのビルド機構がない。初回manifestは、
Light対応の安定版を実際にビルド・検証・公開できた後に生成する。
main由来のコードを過去の安定版の名前で配布しない。

上の画面には「Install Hermes locally」も表示される。今回の受入runでは、Light ZIPに
`resources/agent-payload`がなく、restricted PATH下のlocal backend probeが
`bootstrap-needed`を返し、bootstrap/local agentを起動しないことを確認した。
同じrunで、同一upstream commitのgatewayへの認証、誤secret拒否、Scoop update後の
接続設定保持も確認済みである。ただしこのrunnerはクリーンなWindowsではなく、
安定版の実アップグレードや配布を証明するものではない。

- [x] Windows上のScoop実インストール・更新・ショートカット起動（run 37673954715）。
- [x] gateway接続、認証・接続設定の移行、Lightのローカル動作制約（同run）。
- [ ] 対応安定版でのtag/claim admissionと実ビルド。
- [ ] マージ後のReleases公開・manifest/READMEのmain書き戻し。
- [ ] 安定版での実アップグレードとクリーンなWindowsでのruntime独立性。
- [ ] 既存draftに異なるビルドの部分成果物が残った場合の管理者確認。

上記の未確認項目は、Light対応安定版と明示的な公開許可がないため実行しない。

## 公開ゲートと自動化の追加検証

公開ジョブはリポジトリ変数 `HERMES_DESKTOP_LIGHT_RELEASE_ENABLED` が `true` の場合だけ実行する。
変数は未設定で、今回の作業では有効化しない。対応安定版が出ても、受け入れ確認と
管理者の明示的な許可が終わるまでReleases公開とmain書き戻しを停止する。
検出・read-onlyビルドは公開ゲートと分離している。

publisher自身もActionsのschedule/workflow_dispatchかつmainと明示有効化を要求する。
ローカル開発checkoutやPRで誤って実行しても、API操作やhard resetの前に停止する。
成果物取得に必要な `actions: read` を公開ジョブへ明示した。
`GITHUB_TOKEN` によるpush後の検証は、Desktop Light成功後の `workflow_run` で
Scoop標準CIとAutoupdate validationを起動する。元runが同一リポジトリのmainで
成功した場合だけ、read-onlyで最新mainをcheckoutし、元runの成果物は実行しない。
README生成・検証はpublisher内で完了させる。このmain連携の実運転はマージ前には未検証。

公開処理の回帰テストは、合成ZIP・mock GitHub API・使い捨ての実Gitリポジトリを使う。
初回Draft作成から公開URL照合後のmanifest/README更新、公開済みアセットの再利用と
冪等再実行、異なる部分Draftの拒否、タグ移動、ハッシュ不一致、downgrade、push失敗、
README書き戻しのreadback不一致、公開ゲートを検証する。本番公開の証明ではない。

Windows smokeには、ビルド用Python/Node/Gitを含まないPATHでの起動と、実preloadからの
updater check/applyを追加した。結果は `native-checks.json` と `provenance.json` に残す。
これは初期起動とexternal updaterの確認であり、リモートgateway接続、PATH以外の
インストール済みランタイムからの独立性、安定版の実アップグレードを保証しない。
実CI結果はPRに記録する。

## 配布契約の検証記録

対象commit `3c4b424d8dd16cd77d14842d0e9867d1d9739ed4`について、次の検証を記録する。

| 検証 | 結果 |
| --- | --- |
| Python回帰テスト | 27件成功。Hermes固有のtag/admission、改訂指定、r2/r10の数値順、downgrade拒否、他アプリRelease混在、ページ分割、過去版manifest添付を含む |
| ローカル静的検証 | README生成チェック、Node構文、actionlint、git diff --check成功 |
| [Windows標準CI](https://github.com/takano536/scoop-bucket/actions/runs/37641749710) | Windows PowerShell / PowerShell 7とも成功。Scoop Compare-Versionでr1 < r2 < r10、次の上流版、同版比較を確認 |
| [Autoupdate](https://github.com/takano536/scoop-bucket/actions/runs/37641749687) | 成功 |
| [README](https://github.com/takano536/scoop-bucket/actions/runs/37641749731) | 成功 |
| [Windows Desktop Lightビルド・起動smoke](https://github.com/takano536/scoop-bucket/actions/runs/37641749685) | 成功。公開jobは実行しない |

### 成果物と上流commit

- [Actions artifact](https://github.com/takano536/scoop-bucket/actions/runs/37641749685/artifacts/11492702573)は一時検証用、保持14日。正式配布先ではない。
- 上流commit: `a3ed4a173070e981332e4d879ff6cc8b9efd57ab`
- ZIP: `hermes-desktop-light-preview-a3ed4a1-windows-x64.zip`
- SHA256: `8ab03e5adc3ce4288d53f04d1382e231f928619b912e2516f9cd296007d2879d`
- 170,392,869 bytes / 1,191 entries。ダウンロード後にCRC・hash・Light/external
  stamp・commit一致・agent非同梱を再確認した。
- 二回の実updater IPCはexternal、check supported=false、apply ok=false / commit-build。

これは固定commitのpreviewであり、対応安定版の更新所有・gateway接続・認証移行の
証明ではない。対象安定版、ライセンス通知の同梱、実gateway接続、実更新時の設定保持、
過去版のScoop導入/固定は未確認である。公開実運転はマージと明示的承認後にのみ確認
可能で、公開ゲート未設定、マージ・実Release作成なし。
差分レビューはHermes自身で実施、独立モデルレビューは未実施。
