# 📦 scoop-bucket

個人用の [Scoop](https://scoop.sh) bucket です。
[ScoopInstaller/BucketTemplate](https://github.com/ScoopInstaller/BucketTemplate) を元にしています。

[![CI](https://github.com/takano536/scoop-bucket/actions/workflows/ci.yml/badge.svg)](https://github.com/takano536/scoop-bucket/actions/workflows/ci.yml)
[![Autoupdate validation](https://github.com/takano536/scoop-bucket/actions/workflows/autoupdate.yml/badge.svg)](https://github.com/takano536/scoop-bucket/actions/workflows/autoupdate.yml)
[![Excavator](https://github.com/takano536/scoop-bucket/actions/workflows/excavator.yml/badge.svg)](https://github.com/takano536/scoop-bucket/actions/workflows/excavator.yml)
[![README](https://github.com/takano536/scoop-bucket/actions/workflows/readme.yml/badge.svg)](https://github.com/takano536/scoop-bucket/actions/workflows/readme.yml)

## 🚀 インストール

```powershell
scoop bucket add takano536 https://github.com/takano536/scoop-bucket
scoop install takano536/<アプリ名>
```

導入済みアプリの更新は `scoop update <アプリ名>` で行います。

## 📦 アプリケーション

<!-- BEGIN GENERATED APPS -->

| アプリ | バージョン | 説明 | リンク |
| --- | --- | --- | --- |
| [UDEVGothic-NF](bucket/UDEVGothic-NF.json) | 2.2.0 | UDEV Gothic with Nerd Fonts and ligatures (UDEVGothic35NFLG, half-width/full-width ratio 3:5). | [github.com/yuru7/udev-gothic](https://github.com/yuru7/udev-gothic) |

<!-- END GENERATED APPS -->

## 🤖 自動化

| Workflow | 役割 |
| --- | --- |
| [CI](.github/workflows/ci.yml) | PR・`main` への push 時に、Scoop 標準の manifest テストを Windows PowerShell / PowerShell 7 で実行 |
| [Excavator](.github/workflows/excavator.yml) | 4時間ごと・手動実行で上流の更新を確認し、manifest を default branch に直接 commit・push |
| [Autoupdate validation](.github/workflows/autoupdate.yml) | PR・push・毎日・手動・Excavator 終了後に、版の検出・更新生成・成果物を Windows で検証 |
| [README](.github/workflows/readme.yml) | PR で生成処理を検証し、`main` の変更・Excavator 終了後・手動実行でアプリ一覧を自動更新 |

Excavator と Hermes Desktop Light の `GITHUB_TOKEN` による push は、通常の push workflow を起動しません。
更新検証は両workflowの成功後に `workflow_run` でも起動し、信頼済みの `main` を読み直します。
Desktop Light公開後はScoop標準CIも起動します。READMEはExcavator後のworkflowとDesktop Light publisher自身で
更新し、検証してからcommitします。
README の自動 commit は生成結果に差分がある場合だけ行います。PR や fork のコードを
書き込み権限付きで実行することはありません。

## 🔧 標準テンプレートとの違い

- テンプレート用 README と manifest の見本を、実際の bucket 用の案内に置き換え。
- 通常の manifest テストに加え、黙ったスキップも失敗にする **自動更新経路の検証**を追加。
- `bucket/*.json` から **アプリ一覧を自動生成**。テンプレート全体の自動同期は行いません。

### 自動更新の検証範囲

`bin/test-autoupdate.ps1` は原本のバージョンを保持した一時コピーで、Scoop の
`checkver.ps1 -ForceUpdate -ThrowError` を実行します。実際の `Invoke-AutoUpdate`
呼び出し前後を観測し、対象 manifest の更新処理が1回呼ばれ、正常完了することを
必須条件にします。同じ版の再生成でも合格できますが、黙ったスキップは失敗します。
Scoop の観測箇所が変更された場合も、失敗して見逃しを防ぎます。

- `checkver` / `autoupdate` / アーキテクチャ別 URL の不足、未展開の変数などを検出。
- 再生成 URL からダウンロードし、ハッシュと、指定があれば `extract_dir` を検証。
- 既に最新版なら、再生成した URL・ハッシュ・展開先が登録済みの値と一致するか確認。
- ローカル HTTP サーバーによる回帰テストで、同じ版の再生成・旧版の更新・黙ったスキップなどを検証。

外部サイト障害も失敗として扱います。空 bucket は未検証と明示します。
インストール・アンインストールの hook は実行せず、ダウンロードキャッシュは作成されます。
将来の上流変更、別製品・別版の正常なファイルを取得する問題、PC 上のインストール・GUI 動作、
Excavator の commit・push 権限は保証しません。複雑な hook や複数アーカイブは個別の検証が必要です。

## ビルド済みアプリの配布

このbucketでビルドするアプリは、同じリポジトリのReleasesで配布します。
ZIPはGitにcommitせず、アプリ名でReleaseタグを分けます。

| 項目 | 形式 |
| --- | --- |
| Releaseタグ | `<アプリ名>/v<上流バージョン>-r<改訂番号>` |
| Scoop version | `<上流バージョン>-r<改訂番号>` |
| ZIP | `<アプリ名>-<上流バージョン>-r<改訂番号>-windows-<arch>.zip` |

初回は`r1`、同じ上流版の配布修正は`r2`以降です。同じ内容の再実行では番号を増やさず、
公開済みファイルを上書きしません。新しい上流版では`r1`に戻します。
アプリごとに公開・検証成功後のmanifestを最新版の正本とし、リポジトリ全体の
Latest Releaseや他アプリの公開順には依存しません。

過去のReleaseとZIPも保持します。各Releaseには上流commit・SHA256を記録した
`provenance.json`と、その版のScoop manifestを添付します。
過去版のZIPは[Releases](https://github.com/takano536/scoop-bucket/releases)から取得できます。
過去版manifestの`checkver`は現在の正常版を参照するため、導入後の更新は最新版へ進みます。
過去版への固定・ダウングレードは通常の最新版インストールとは別の操作です。
詳細は[配布ルール](docs/distribution-policy.md)を参照してください。

## Hermes Desktop Light

`Hermes Desktop Light`（[workflow](.github/workflows/hermes-desktop-light.yml)）は、4時間ごとに
公式`NousResearch/hermes-agent`の`main`を完全なcommit SHAへ固定し、Light対応のmanaged
builder contractがそのcommitにある場合だけ、Windows x64のリモート専用開発版をCIでビルドします。
展開済みElectronアプリをZIPにし、実際の起動・再起動、ユーザーデータの保持、Desktop Lightの
構成・更新所有者・SHA256を検証してから、開発用Releaseへ公開します。

**DEVELOPMENT BUILD — NOT STABLE** です。開発版のScoop versionは
`0.0.0-alpha.dev.<devSeq>-r<revision>`、tagは
`hermes-desktop-light/dev/v<version>-<upstreamの完全なcommit SHA>`、ZIPは
`hermes-desktop-light-dev-<version>-<upstreamの完全なcommit SHA>-windows-x64.zip`です。
`devSeq`はこのアプリの公開済み開発Releaseからだけ算出し、同じcommit・同じbuild
conditions fingerprintの再実行では番号を増やさず、同じcommitの配布修正だけを
明示的なworkflow_dispatchで`r2`以降にします。scheduleは`r1`以外を生成しません。
過去のRelease・ZIP・manifest・`metadata/hermes-desktop-light-dev.json`は保持し、
manifestのcheckver/autoupdateはこのpointerと検証済みReleaseだけを参照します。

publish gateは初期状態で無効です。開発版を公開するには管理者が
`HERMES_DESKTOP_LIGHT_DEV_RELEASE_ENABLED=true`を設定する必要があります（このPRでは設定しません）。
Light対応の安定版をこのアプリ用にビルド・Windows検証・公開できた時点で、開発追従は一方向に終了し、
`metadata/hermes-desktop-light-channel.json`へ遷移を記録します。その後は
`HERMES_DESKTOP_LIGHT_RELEASE_ENABLED=true`の安定版だけを追従し、開発publisherは安定版Release
または遷移記録が存在すると即時拒否します。安定版versionはすべての開発版よりScoopで大きくなるため、
channelを自動切替したり、開発版へ戻ったりしません。stable gateもこのPRでは設定しません。

`v2026.9.24`はLight非対応ですが、Light対応の`main`開発commitを公開すれば現在でも
インストールできます。Release title/body、manifest description/notes、READMEには常に
`development build`/`not stable`を明記します。ReleaseはGitHub prereleaseかつ`latest=false`です。
各Releaseには上流commit、MIT LICENSEのSHA256、build conditions fingerprint、artifact SHA256、
provenance.jsonとその版のScoop manifestを添付します。公開URLとSHA256を再検証してから
`bucket/hermes-desktop-light.json`とアプリ一覧を`main`へ更新し、失敗時はmanifestを変更しません。

配布は非公式・未署名のx64ビルドで、ローカルのPython・agentは含まず、既存のHermes gatewayへの
接続が必要です。gateway接続、必要なランタイム、接続・認証情報の実アップグレード移行は、
stable公開を有効化する前にWindowsで受け入れ確認が必要です。

[実Windows CIの検証結果と画面](docs/hermes-desktop-light-verification.md)を記録しています。
起動検証はgateway接続や認証移行の証明ではありません。

## 🛠️ メンテナンス

manifest を追加・変更すると、マージ後にアプリ一覧へ反映されます。
一覧の生成範囲はコメントで囲まれた部分だけです。表は直接編集せず、manifest を変更してください。

ローカルで README を生成・検証するには Python 3 を使います（追加パッケージ不要）。

```powershell
python scripts/update-readme.py
python scripts/update-readme.py --check
python -m unittest discover -s tests -p test_readme.py -v
```

更新経路の検証は Scoop・PowerShell 7・7-Zip がある Windows 環境で実行できます。

```powershell
.\bin\test-autoupdate.ps1 -ScoopHome (scoop prefix scoop)
```

GitHub Actions の手動実行：

```powershell
gh workflow run excavator.yml --repo takano536/scoop-bucket --ref main
gh workflow run autoupdate.yml --repo takano536/scoop-bucket --ref main
gh workflow run readme.yml --repo takano536/scoop-bucket --ref main
```

manifest の仕様は [App Manifests](https://github.com/ScoopInstaller/Scoop/wiki/App-Manifests) を参照してください。
