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

[Hermes Desktop Light](.github/workflows/hermes-desktop-light.yml) は4時間ごとに公式
`NousResearch/hermes-agent` の安定リリースを確認し、Windows x64 のリモート専用クライアントを
CIでビルドします。展開済みElectronアプリをZIPにし、実際の起動・再起動、ユーザーデータの保持、
Desktop Lightの構成・更新所有者・SHA256を検証してから、このbucketのReleasesへ公開します。
公開URLの再検証後に `bucket/hermes-desktop-light.json` とアプリ一覧を `main` へ直接更新します。
既存の公開成果物は上書きせず、ビルドや検証の失敗時には既存manifestを維持します。

公開は初期状態では無効です。Light対応安定版でのWindows受け入れ確認を終え、
管理者が明示的に配布を許可した後にだけ、リポジトリ変数
`HERMES_DESKTOP_LIGHT_RELEASE_ENABLED=true` で公開を有効化します。このPRでは変数を設定しません。
有効化後、対応安定版のビルド・検証・公開が成功したときだけ初回manifestを生成します。
現在の最新安定版 `v2026.9.24` はLight非対応のため、まだインストールできません。
PRでは固定した上流コミットの検証ビルドだけを実行し、配布・manifest更新は行いません。
旧タグへのmainのコードの混入や、プレリリースの追従は行いません。

配布は非公式・未署名のx64ビルドです。ローカルのPython・エージェントは含まず、
既存のHermes gatewayへの接続が必要です。Scoopがアプリ更新を所有し、設定はアプリの
ユーザーデータ領域に残します。gateway接続、必要なランタイム、接続・認証情報の
実アップグレード移行は、公開を有効化する前にWindowsで受け入れ確認が必要です。
初回公開後は既存Excavatorも、このbucketで検証済みの
Desktop Lightリリースだけを追従できます。

[実Windows CIの検証結果と画面](docs/hermes-desktop-light-verification.md)を記録しています。
起動検証はgateway接続や認証移行の証明ではありません。検証版の初回画面にはローカル
インストールの選択肢も表示されるため、LightのUI/実行制約は安定版での追加確認が必要です。

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
