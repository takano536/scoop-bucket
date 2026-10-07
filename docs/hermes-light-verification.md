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

## 未確認事項と配布開始条件

最新の公開安定版 `v2026.9.24` にはLightのビルド機構がない。初回manifestは、
Light対応の安定版を実際にビルド・検証・公開できた後に生成する。
main由来のコードを過去の安定版の名前で配布しない。

上の画面には「Install Hermes locally」も表示される。Lightとしての非同梱構成と
起動は確認済みだが、リモート専用のUI/実行制約、gateway接続、接続/認証設定の
実アップグレード移行は確認できていない。表示だけからローカル動作の可否を断定しない。

## ライセンス通知と名称・ロゴの公開条件

PR #4 の Windows 成果物（[run 37642669034](https://github.com/takano536/scoop-bucket/actions/runs/37642669034)）を調査した。ZIP は 1,191 エントリで、`LICENSE.electron.txt` と
`LICENSES.chromium.html` は既に含まれていた。一方、上流の `LICENSE`、第三者通知、
非公式配布表示は含まれていなかった。`resources/app.asar` のヘッダーを読み取り、
`dist/node_modules/get-windows` と `dist/node_modules/node-pty` が同梱され、その他の
desktop production dependency は bundle に入る構成であることを確認した。

今回のWindows buildでは、対象commitの上流 `LICENSE` をそのまま `LICENSE` としてコピーし、
上流 `apps/desktop/package.json` の `dependencies`（80）、`optionalDependencies`（1）、
`devDependencies`（31）を起点に、インストール済みpackageの依存を再帰的に辿って
`THIRD-PARTY-NOTICES.txt` を生成する。到達したworkspace package（Lightでは
`@hermes/shared`）については自身のdependencies/optionalDependenciesに加えて
devDependenciesも辿る。lockfileで`optional`とされたプラットフォーム別packageの
未インストールな子依存だけは、対象OSに存在しないため収集対象から除外する。
license fileまたはpackage metadataから判定できない
同梱候補packageが一つでもあればbuildを失敗させる。
`UNOFFICIAL-BUILD.txt` には上流ref/commit、bucket commit、workflow URL、各licenseファイルの
場所を記録する。`provenance.json` には3ファイルのSHA256と対象package数を記録し、
publish側はZIP内の存在・SHA256・上流MIT copyright行をdata-onlyで検証する。

PR #6 の成果物ではsourcemapが生成されていなかったため、bundleからpackage名を
完全列挙する方式ではなく、上記のdevDependenciesを含む保守的なsupersetを採用した。
`dist/assets/vendor-react-*.js` にReact実装、`dist/assets/katex-*.js` と
`mermaid-*.js` に第三者bundle、`dist/electron-main.mjs` に`node-pty`と
esbuild由来のbundled license bannerがあることを、ASAR header offsetと
`resources/app.asar.unpacked`のファイルだけで確認した。`desktop_prepare.py`の
Light workspace選択は`apps/desktop`のみで、`web`/`ui-tui`はLightではbuildされない。
将来Lightのworkspace選択を拡張する場合は、そのworkspaceを起点に同じ再帰収集を行う。

manifestの`license`は、Hermes Agent本体の上流`package.json`/`LICENSE`がMITであるため
`MIT`のままとする。依存packageごとに異なるlicenseの集合を一つの正確なSPDX式へ
置き換えることはできないため、manifestへ`Freeware`等を記載せず、同梱の
`THIRD-PARTY-NOTICES.txt`で各依存のlicense本文を示す。

名称・ロゴの条件を、対象commitの[README](https://github.com/NousResearch/hermes-agent/blob/a3ed4a173070e981332e4d879ff6cc8b9efd57ab/README.md)、
desktopの[identity](https://github.com/NousResearch/hermes-agent/blob/a3ed4a173070e981332e4d879ff6cc8b9efd57ab/apps/desktop/product-identity.cjs)、
[electron-builder設定](https://github.com/NousResearch/hermes-agent/blob/a3ed4a173070e981332e4d879ff6cc8b9efd57ab/apps/desktop/electron-builder.config.cjs)、
[Contributing](https://hermes-agent.nousresearch.com/docs/developer-guide/contributing)、
および[公式サイト](https://hermes-agent.nousresearch.com/)で検索した。これらは
Nous ResearchがHermes Agentを作成・提供すること、Hermes/Hermes Lightの名称・画像・
アイコンを使うことは示すが、第三者による再配布での商標・ロゴ利用許諾やブランド
ガイドラインは示していない。MIT licenseも商標の許諾を与えない。このため、非公式・
unsigned表示を追加しても、名称・ロゴの利用条件は**未確認**であり、公開前に上流の
書面による許諾または明確なブランド規則を確認するまで配布開始の阻害条件とする。


- 対応安定版でのtag/claim admissionと実ビルド。
- Windows上のScoop実インストール・更新・ショートカット起動。
- gateway接続、認証・接続設定の移行、Lightのローカル動作制約。
- マージ後のReleases公開・manifest/READMEのmain書き戻し。
- 既存draftに異なるビルドの部分成果物が残った場合、上書きせず停止する。
  管理者がdraftを確認する必要がある。公開済みreleaseは書き戻し再試行時に再利用する。

これらを実行済みとみなさず、PRはDraftで保持する。

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
