# Hermes Light 検証

## 実Windows CI

- [ビルド・起動検証](https://github.com/takano536/scoop-bucket/actions/runs/37620186448)
- 上流: `NousResearch/hermes-agent@a3ed4a173070e981332e4d879ff6cc8b9efd57ab`
- 検証ZIP: `hermes-agent-light-preview-a3ed4a1-windows-x64.zip`
- SHA256: `b83ff46eaed9e30600f7dafcb2ed69c0521bb50ff7dc925e6b5362110d325ec9`
- ZIP: 170,392,861 bytes / 1,191 entries。ダウンロード後のSHA256照合とZIP CRC検証に成功。
- Packaged Electronの起動・再起動とlocalStorage保持を検証。`payload=light`、
  `updateMechanism=external`、source commit一致、`resources/agent-payload` 非同梱を確認。
- 設定先にはCIの一時ディレクトリを使用。実gatewayや認証情報を与えていない。
- これはPR専用の検証成果物。安定版としての公開・manifest登録はしていない。

![Windows CIでの初回起動画面](images/unformatted/hermes-light-preview.png)

画像はScoop標準のテキスト整形テストの対象外である `unformatted` 領域に置く。

## 成果物の保存先とskip条件

- 対象ソースのLight identityと管理されたbuilderを検査し、非対応・必要ファイルなしは
  正常なskipとする。API障害・権限エラーは非対応と混同せず失敗させる。
- PRはLight対応を確認した固定commitのpreviewビルド。安定版の検出とは独立している。
- Windows runner上では `upstream/apps/desktop/release/win-unpacked` を直接ZIP化し、
  `output/` にZIP・provenance・smoke証拠を置く。ここでの `release/` は上流の
  ローカルビルド出力ディレクトリであり、GitHub Releasesへの公開ではない。
- CIからの保存先はActions Artifactsの `hermes-light-windows-x64`（保持14日）。
  リポジトリへバイナリをcommitせず、PRからReleasesへも公開しない。
- 将来のScoop配布用GitHub Releases公開は、mainかつ明示有効化されたpublisherのみ。
  現在は無効のままで、マージや公開の有効化は今回の作業に含めない。

## Windows受入ジョブ（このPRで追加）

`.github/workflows/hermes-light.yml` の `acceptance` job は、`build` の
Actions ArtifactをWindows runnerへ渡し、実行時だけ作る
`hermes-agent-light-acceptance` manifestで次を確認する。manifestは
`%RUNNER_TEMP%` に置き、bucket/へ追加しない。

- Scoop install/update/uninstall、Start Menuの`.lnk`経由起動、アプリ本体と
  shortcutの削除、`HERMES_HOME`/Desktop user-dataの残存。
- `dumpbin /DEPENDENTS` によるパッケージのexeとnative `.node` imports、
  `vcruntime`/`msvcp`等の同梱有無。GitHub-hosted runnerはクリーンなWindows
  ではないため、起動成功だけではVC++ runtimeのクリーン環境独立性を証明しない。
- 上流checkoutと同じcommitの `hermes serve --skip-build` をlocalhostで起動し、
  job内で生成した `HERMES_DASHBOARD_SESSION_TOKEN` をmaskして、Desktopの
  実HTTP+WebSocket接続を確認する。接続設定はUIクリックではなく、CDPから
  アプリのpreload bridge IPC（`applyConnectionConfig`、
  `getConnectionConfig`、`getGatewayWsUrl`）を呼ぶ。Scoop update後は、保存済み
  secretからbridgeがmintしたWS URLだけをrendererへ渡し、renderer自身が
  `session.list` JSON-RPCを送り、返却された`result.sessions`を検証する。
  別にNodeから`/api/sessions`を呼ぶ結果はdirect gateway probeと明示する。
  provider/LLM credentialは渡さない。
- `resources/agent-payload`なし、local backend probeが`bootstrap-needed`で
  bootstrapを実行しないこと、remote接続設定、Scoop更新後の設定・認証・
  authenticated round-trip保持、in-app updaterの`external`/unsupported拒否と
  app tree不変を確認する。

改訂後の実Windows受入runは成功した。

- run: [37670616565](https://github.com/takano536/scoop-bucket/actions/runs/37670616565)
- acceptance job: [112968478718](https://github.com/takano536/scoop-bucket/actions/runs/37670616565/job/112968478718)
- upstream: `NousResearch/hermes-agent@a3ed4a173070e981332e4d879ff6cc8b9efd57ab`
- このrunのbucket commit: `fe77bec`
- build ZIP: `hermes-agent-light-preview-a3ed4a1-windows-x64.zip`
- ZIP SHA256: `1f5e10655947b635a9b62e271db6418c7cc0883f86884e633c57c6789039741e`
- acceptance artifact: `hermes-light-windows-acceptance`（保持14日）
- Scoopのtest-only before/after version、Start Menu shortcut、uninstall後のapp/shortcut削除と
  user-data残存を確認。preload bridge IPCを通じたアプリ側の認証済み`session.list`
  WebSocket RPC、同一gatewayへのdirect Node `/api/sessions` probeの`200`、誤secretの
  `401`、Scoop update後の設定・tokenSet保持を確認。
- 異なるLight対応upstream commitの同一runビルドはまだないため、before/afterは
  同じZIPを異なるtest-only versionとして使った。これはScoop更新時の設定保持を
  検証するが、異なるバイナリ間のmigrationは証明しない。
- PE調査では検査対象のruntime importsと同梱CRT DLLが空だった。ただしrunnerIsCleanは
  `false`であり、クリーンなWindowsへのruntime独立性は未証明。
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

- [x] Windows上のScoop実インストール・更新・ショートカット起動（run 37670616565）。
- [x] gateway接続、認証・接続設定の移行、Lightのローカル動作制約（同run）。
- [ ] 対応安定版でのtag/claim admissionと実ビルド。
- [ ] マージ後のReleases公開・manifest/READMEのmain書き戻し。
- [ ] 安定版での実アップグレードとクリーンなWindowsでのruntime独立性。
- [ ] 既存draftに異なるビルドの部分成果物が残った場合の管理者確認。

上記の未確認項目は、Light対応安定版と明示的な公開許可がないため実行しない。

## 公開ゲートと自動化の追加検証

公開ジョブはリポジトリ変数 `HERMES_LIGHT_RELEASE_ENABLED` が `true` の場合だけ実行する。
変数は未設定で、今回の作業では有効化しない。対応安定版が出ても、受け入れ確認と
管理者の明示的な許可が終わるまでReleases公開とmain書き戻しを停止する。
検出・read-onlyビルドは公開ゲートと分離している。

publisher自身もActionsのschedule/workflow_dispatchかつmainと明示有効化を要求する。
ローカル開発checkoutやPRで誤って実行しても、API操作やhard resetの前に停止する。
成果物取得に必要な `actions: read` を公開ジョブへ明示した。
`GITHUB_TOKEN` によるpush後の検証は、Hermes Light成功後の `workflow_run` で
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
