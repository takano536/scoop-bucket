# Hermes Desktop Light 検証

## 実Windows CI

- [ピン留めdevelopment build・起動検証 run 37723915669](https://github.com/takano536/scoop-bucket/actions/runs/37723915669) は成功。
- 上流: `NousResearch/hermes-agent@08165d58931841cee713468ae89032af7c57060a`（40桁SHA）。
- version: `0.0.0-alpha.dev.1-r1`。Release tag/公開用ZIP名はこの完全SHAに結び付く。
- exact MIT LICENSE SHA256: `821556e6336796450ab852d375117b48a4887e71d255794fd6318d99982a5ab6`。
- conditions fingerprint: `8fdbc5039c369cd7fda60b6eece7506f7d9a5f790c128b8bdfa971bf4c22d1f9`。
- ZIP SHA256: `1443bf86c8afbb60fb71e3f239352388c2a5fb2eb0b36d1ae3086e1393215d5b`。
- provenanceのsourceRef/commit、install-stampのcommit、artifact名はいずれもこの40桁SHAに一致。
- ZIPは1,193 entriesで、`resources/install-stamp.json`、`LICENSE.electron.txt`、
  `LICENSES.chromium.html`を含み、`resources/agent-payload`は含まない。native smoke
  （2回起動・renderer読込・再起動後localStorage保持・external updater）に成功した。
- PR実行のためpublishはskipされ、GitHub Release・manifest・READMEの書き戻しは行っていない。

## 成果物の保存先とskip条件

- schedule/workflow_dispatchは実行開始時の`main`を完全なcommit SHAへ解決し、そのSHAの
  Light identityと管理されたbuilder contractを検査する。非対応・必要ファイルなしは正常なskip、
  API障害・権限エラーは非対応と混同せず失敗とする。scheduleはstable gateが有効でstable
  admission（identity・builder・annotated claim）を満たす場合だけstableを計画し、それ以外は
  developmentを計画する。選択channelのgateが無効なscheduleはbuildせずskipする。
- PRも同じmain pinのdevelopment buildで、bucket Release一覧を参照しない。exact commitの
  MIT LICENSE本文とSHA256、conditions fingerprintを確認し、`provenance.json`へ記録する。
  PRではpublish/writebackしない。
- Windows runner上では`upstream/apps/desktop/release/win-unpacked`を直接ZIP化し、
  `output/`にZIP・provenance・smoke証拠を置く。ここでの`release/`は上流のローカル
  ビルド出力であり、GitHub Releasesへの公開ではない。
- CIからの保存先はActions Artifactsの`hermes-desktop-light-windows-x64`（保持14日）。
  リポジトリへバイナリをcommitせず、PRからReleasesへも公開しない。
- 開発Releaseは`hermes-desktop-light/dev/` tag、prerelease、`latest=false`で保持し、
  title/body、manifest description/notes、READMEに**DEVELOPMENT BUILD — NOT STABLE**を明記する。
  `metadata/hermes-desktop-light-dev.json`は最後に公開・URL+SHA256検証されたpointerだけを示す。
  Scoop manifestはこのpointerと同じappの検証済みReleaseだけを参照する。

## 開発channelの一方向transition

最新の公開安定版`v2026.9.24`にはLightのビルド機構がないため、開発版はLight対応main commit
の公開で先にインストール可能になる。Light対応stableをこのapp向けにbuild・Windows検証・公開
できた時点で開発追従を終了し、`metadata/hermes-desktop-light-channel.json`へversion/tag、
upstream commit、SHA256を記録する。そのstable Releaseまたはmarkerがある場合、dev publisherは
hard-refuseする。manifestは自動切替せず、Scoop version順（全dev < stable）によりbounceしない。
stable公開・manifest書き戻しは、stable gateの明示許可後だけ行う。


- Light対応stableのtag/claim admissionと実ビルド。
- Windows上のScoop実インストール・更新・ショートカット起動。
- gateway接続、認証・接続設定の移行、Lightのローカル動作制約。
- main開発版とstableの各Release公開後、manifest/READMEのmain書き戻し。
- 既存draftに異なるビルドの部分成果物が残った場合、上書きせず停止する。
  管理者がdraftを確認する必要がある。公開済みReleaseは書き戻し再試行時に再利用する。


## 公開ゲートと自動化の追加検証

開発公開ジョブはリポジトリ変数`HERMES_DESKTOP_LIGHT_DEV_RELEASE_ENABLED`、
stable公開ジョブは`HERMES_DESKTOP_LIGHT_RELEASE_ENABLED`が`true`の場合だけ実行する。
両変数は未設定で、このPRでは有効化しない。mainのread-only plan/build/smokeはgateと分離する。
scheduleはstable gateが有効でstable admissionを満たす場合だけstable buildを計画する。
stable buildが失敗・skipしてstable Releaseが実際に公開されるまでdev manifestを維持し、
dev channelへbounceしない。developmentを選んだscheduleは`r1`だけを許可し、同じcommitの
条件変更による`r2+`は明示的なworkflow_dispatchだけを許可する。

publisher自身もActionsのschedule/workflow_dispatchかつmainと、channel固有の明示gateを要求する。
ローカルcheckoutやPRで誤って実行しても、API操作やhard resetの前に停止する。成果物取得に必要な
`actions: read`を公開jobへ明示した。draft作成後は`prerelease=true`/`latest=false`をread backし、
公開URLのSHA256を検証してからpointer、manifest、READMEをcommitする。既存assetを上書きしない。
Scoop checkver/autoupdateは、このappの公開済みpointer/releaseだけを参照する。

`workflow_run`は、指定したschedule/workflow_dispatch実行が完了したというGitHubの完了イベントで
発火する。publisherが`GITHUB_TOKEN`でmanifest/READMEを書き戻しても、そのpushは通常のpush
workflowを再帰発火させないため、書き戻し後の検証経路としてこの完了イベントを使う。
publisher成功時はpush後の`git rev-parse HEAD`を`written-back-sha.txt`にしてActions Artifactへ
保存する。CIとAutoupdate validationの`resolve-target` jobはその小さなArtifactだけを読み、
SHAが`^[0-9a-f]{40}$`であることを検証して、書き戻された正確なcommit SHAをcheckoutする。
publishがskipされてArtifactがない場合は、元`workflow_run.head_sha`を同じ形式で検証して使う。
したがってmutableな「最新main」や元runの成果物を実行せず、checkoutしたcommit上のScoop標準
CI・checkver/autoupdate検証をread-onlyで行う。
このmain連携と実GitHub Releaseの実運転はマージ前には未検証。

公開処理の回帰テストは、合成ZIP・mock GitHub API・使い捨ての実Gitリポジトリを使う。
初回Draft作成から公開URL照合後のmanifest/README更新、公開済みアセットの再利用と
冪等再実行、異なる部分Draftの拒否、タグ移動、ハッシュ不一致、downgrade、push失敗、
README書き戻しのreadback不一致、公開ゲートを検証する。本番公開の証明ではない。

Windows smokeには、ビルド用Python/Node/Gitを含まないPATHでの起動と、実preloadからの
updater check/applyを追加した。結果は `native-checks.json` と `provenance.json` に残す。
これは初期起動とexternal updaterの確認であり、リモートgateway接続、PATH以外の
インストール済みランタイムからの独立性、安定版の実アップグレードを保証しない。
実CI結果はPRに記録する。
