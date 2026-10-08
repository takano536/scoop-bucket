# Hermes Desktop Light 検証

## 実Windows CI

- [ビルド・起動検証](https://github.com/takano536/scoop-bucket/actions/runs/37620186448)
- 上流: `NousResearch/hermes-agent@a3ed4a173070e981332e4d879ff6cc8b9efd57ab`
- 検証ZIP: `hermes-desktop-light-preview-a3ed4a1-windows-x64.zip`（旧PR runの履歴artifact）
- SHA256: `b83ff46eaed9e30600f7dafcb2ed69c0521bb50ff7dc925e6b5362110d325ec9`
- ZIP: 170,392,861 bytes / 1,191 entries。ダウンロード後のSHA256照合とZIP CRC検証に成功。
- Packaged Electronの起動・再起動とlocalStorage保持を検証。`payload=light`、
  `updateMechanism=external`、source commit一致、`resources/agent-payload` 非同梱を確認。
- 設定先にはCIの一時ディレクトリを使用。実gatewayや認証情報を与えていない。
- これは旧PR runの履歴検証成果物。現在のPRはpreview固定SHAではなく、pinしたmain commitの
  development buildをWindowsで検証し、安定版としての公開・manifest登録はしていない。

![Windows CIでの初回起動画面](images/unformatted/hermes-desktop-light-preview.png)

画像はScoop標準のテキスト整形テストの対象外である `unformatted` 領域に置く。

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

この文書7〜13行のpreview名artifactは旧runの履歴であり、Scoop Release公開・manifest登録を
証明するものではない。main開発版の実Windows build/smoke結果は、最初の有効なCI run後に
commit hash、LICENSE hash、conditions fingerprint、ZIP SHA256とともに追記する。

上の画面には「Install Hermes locally」も表示される。Lightとしての非同梱構成と
起動は確認済みだが、リモート専用のUI/実行制約、gateway接続、接続/認証設定の
実アップグレード移行は確認できていない。表示だけからローカル動作の可否を断定しない。

- Light対応stableのtag/claim admissionと実ビルド。
- Windows上のScoop実インストール・更新・ショートカット起動。
- gateway接続、認証・接続設定の移行、Lightのローカル動作制約。
- main開発版とstableの各Release公開後、manifest/READMEのmain書き戻し。
- 既存draftに異なるビルドの部分成果物が残った場合、上書きせず停止する。
  管理者がdraftを確認する必要がある。公開済みReleaseは書き戻し再試行時に再利用する。

これらを実行済みとみなさず、PRはDraftで保持する。

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

`GITHUB_TOKEN`によるpush後の検証は、Desktop Light成功後の`workflow_run`でScoop標準CIと
Autoupdate validationを起動する。元runが同一リポジトリのmainで成功した場合だけ、read-onlyで
最新mainをcheckoutし、元runの成果物は実行しない。README生成・検証はpublisher内で完了させる。
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
