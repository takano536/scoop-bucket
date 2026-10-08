# Hermes Desktop Light 検証

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

## 未確認事項と配布開始条件

最新の公開安定版 `v2026.9.24` にはLightのビルド機構がない。初回manifestは、
Light対応の安定版を実際にビルド・検証・公開できた後に生成する。
main由来のコードを過去の安定版の名前で配布しない。

上の画面には「Install Hermes locally」も表示される。Lightとしての非同梱構成と
起動は確認済みだが、リモート専用のUI/実行制約、gateway接続、接続/認証設定の
実アップグレード移行は確認できていない。表示だけからローカル動作の可否を断定しない。

- 対応安定版でのtag/claim admissionと実ビルド。
- Windows上のScoop実インストール・更新・ショートカット起動。
- gateway接続、認証・接続設定の移行、Lightのローカル動作制約。
- マージ後のReleases公開・manifest/READMEのmain書き戻し。
- 既存draftに異なるビルドの部分成果物が残った場合、上書きせず停止する。
  管理者がdraftを確認する必要がある。公開済みreleaseは書き戻し再試行時に再利用する。

これらを実行済みとみなさず、PRはDraftで保持する。

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
