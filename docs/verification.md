# 検証手順

この手順は、リポジトリのルートで実行する共通の入口である。ローカルで実行できない
Windows専用処理は、対応するGitHub Actionsの項目として記載する。アプリをこのbucket
自身がビルドして配布する場合の詳細な受入条件、公開ゲート、実行済み・未確認の状態は、
それぞれのアプリ固有文書を参照する。

## ローカル検証

### Pythonテスト

`tests/` のPythonテストを標準ライブラリの`unittest`で実行する。

```bash
python3 -m unittest discover -s tests -v
```

PowerShellテストは含まれない。個別アプリのテストがある場合も、この共通コマンドで
実行される。追加の前提条件や受入条件はアプリ固有文書に記載する。

### README生成

READMEのアプリ一覧は`scripts/update-readme.py`がマーカー間を生成する。差分を作らずに
確認するには次を実行する。

```bash
python3 scripts/update-readme.py --check
```

生成自体を確認する場合は`python3 scripts/update-readme.py`を実行した後、もう一度
`--check`を実行する。

### GitHub Actions構文（インストール済みの場合）

`actionlint`が利用できる場合だけ実行する。未インストールならこの項目をスキップする。

```bash
if command -v actionlint >/dev/null 2>&1; then
  actionlint
else
  echo 'actionlint is not installed; skipped'
fi
```

### 空白エラー

作業ツリーと`origin/main`との差分を確認する。

```bash
git diff --check
git diff --check origin/main...
```

### Windows専用テスト

次のPowerShell処理はScoop、PowerShell、7-Zipなどを必要とするため、通常はWindows
runner上のworkflowで実行する。

```powershell
.\tests\distribution-versions.ps1 -ScoopHome (scoop prefix scoop)
.\tests\autoupdate-regression.ps1 -ScoopHome (Resolve-Path .\scoop_core)
.\bin\test-autoupdate.ps1 -ScoopHome (Resolve-Path .\scoop_core)
.\bin\test.ps1
```

`bin/test.ps1`はPesterとBuildHelpersを要求し、リポジトリのPesterテストを実行する。
`Scoop-Bucket.Tests.ps1`はScoop側の`Import-Bucket-Tests.ps1`を読み込む。

## CI/CDワークフロー

ここでは共通workflowの役割と入口だけを示す。bucket-built distributionや個別アプリの
build・smoke・公開条件は、該当アプリの契約に従う。

### CI ([../.github/workflows/ci.yml](../.github/workflows/ci.yml))

`main`/`master`へのpush、Pull Request、`workflow_dispatch`で起動する。信頼できる同一
リポジトリのmain上のworkflow完了を起点にした検証も、元runの条件を確認して実行する。
Windowsの`powershell`と`pwsh`のmatrixで、Scoop標準テストと、このbucketが定める
共通回帰テストをread-onlyで実行する。`tests/distribution-versions.ps1`は、該当する
bucket-built manifestが配布改訂を使う場合だけ、その版の比較順を確認する。通常の
上流配布物manifestに`rN`を要求するものではない。

### Autoupdate validation ([../.github/workflows/autoupdate.yml](../.github/workflows/autoupdate.yml))

`main`/`master`へのpush、Pull Request、`workflow_dispatch`、信頼できるworkflow完了、
UTC 06:43のdaily schedule（`43 6 * * *`）で起動する。Windows PowerShellで、一時fixture
を使ったcheckver/autoupdate回帰と、manifestのコピーに対するlive URL・hash・
`extract_dir`検証をread-onlyで行う。アプリのinstallやhookは実行しない。

### README ([../.github/workflows/readme.yml](../.github/workflows/readme.yml))

`bucket/**`、`README.md`、README生成スクリプト・テスト・workflowを変更したpush/PR、
`workflow_dispatch`、Excavatorのworkflow完了で検証を起動する。Pythonテスト、README
生成、`--check`を実行する。READMEの書き戻しはPull Requestでは行わず、条件を満たす
main上のpush・手動実行・workflow完了だけで行う。

### Excavator ([../.github/workflows/excavator.yml](../.github/workflows/excavator.yml))

手動実行と、UTCの4時間ごとのcron（`20 */4 * * *`）で起動する。Windows runnerで
Scoopの自動更新処理を実行し、必要な書き戻し権限を持つ。

### Hermes Light ([../.github/workflows/hermes-light.yml](../.github/workflows/hermes-light.yml))

Hermes Lightのbuild、smoke、bucket-built distributionとしての受入条件、公開ゲート、
成果物対応、実行済み・未確認事項は
[Hermes Light検証](hermes-light-verification.md)にまとめる。この共通手順では、
Hermes固有のトリガーや一時的な検証状態を重複して記載しない。

### その他の自動化

- [Pull Requests](../.github/workflows/pull_request.yml): Pull Requestのopenedと、
  `/verify`を含むissue commentのcreatedを受け、WindowsでScoopのGitHub Actionを実行する。
- [Issues](../.github/workflows/issues.yml): issueのopenedまたは`verify` label付きlabeledを
  受け、WindowsでScoopのGitHub Actionを実行する。

## CIで検証される範囲

| 項目 | workflow | 条件・内容 |
| --- | --- | --- |
| Scoopのmanifestテスト | CI | WindowsのPowerShell / pwsh matrixでPesterを実行する。 |
| bucket-built distributionの改訂順 | CI | 該当アプリの契約が定める版形式だけを`Compare-Version`で確認する。 |
| autoupdate回帰 | Autoupdate validation | 一時fixtureでPowerShellの回帰ケースを実行する。 |
| live autoupdate | Autoupdate validation | 実URLを取得し、hashと`extract_dir`を確認する。 |
| READMEテスト・生成 | README | Python unittest、生成、`--check`を実行する。 |
| アプリ固有のbuild・受入・公開 | 各アプリのworkflow | アプリ固有文書の契約とゲートに従う。 |

## PRマージ前後の扱い

Pull Requestでは、変更されたpathに対応するread-only検証workflowを実行する。README生成や
自動更新の書き戻しなど、write権限を持つjobはPull Requestでは実行しない。アプリを
このbucket自身がビルドして配布する場合は、受入条件、公開ゲート、成果物と上流commitの
対応、未確認事項をアプリ固有文書に記録する。

Windows上のScoop実インストール、実Release公開、外部サービス接続、認証移行などは、
共通のローカル手順やPull Requestだけでは検証済みとしない。実行範囲と阻害条件を各
アプリの文書に明記する。

## 関連リンク

- [配布ルール](distribution-policy.md)
- [Hermes Light検証](hermes-light-verification.md)
- [AGENTS.md](../AGENTS.md)
