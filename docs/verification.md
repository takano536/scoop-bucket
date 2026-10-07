# 検証手順

この手順は、リポジトリのルートで実行する。ローカルで実行できないWindows専用処理は、対応するGitHub Actionsの項目として記載する。

## ローカル検証

### Pythonテスト

最初に、`tests/` のPythonテストを標準ライブラリの `unittest` で実行する。

```bash
python3 -m unittest discover -s tests -v
```

このコマンドは `test_distribution.py`、`test_hermes_light*.py`、`test_readme.py` などを実行する。PowerShellテストは含まれない。pytestはインストールされていないため使用しない。

### README生成

READMEのアプリ一覧は `scripts/update-readme.py` がマーカー間を生成する。差分を作らずに確認するには次を実行する。

```bash
python3 scripts/update-readme.py --check
```

生成自体を確認する場合は `python3 scripts/update-readme.py` を実行した後、もう一度 `--check` を実行する。

### Node.js構文

Hermes LightのsmokeスクリプトをNode.jsで構文検査する。

```bash
node --check scripts/smoke-hermes-light.cjs
```

### GitHub Actions構文（インストール済みの場合）

`actionlint` が利用できる場合だけ実行する。未インストールならこの項目をスキップする。

```bash
if command -v actionlint >/dev/null 2>&1; then
  actionlint
else
  echo 'actionlint is not installed; skipped'
fi
```

### 空白エラー

作業ツリーと `origin/main` との差分を確認する。

```bash
git diff --check
git diff --check origin/main...
```

### Windows専用テスト

次のPowerShell処理はScoop、PowerShell、7-Zipなどを必要とするため、通常はWindows runner上のworkflowで実行する。

```powershell
.\tests\distribution-versions.ps1 -ScoopHome (scoop prefix scoop)
.\tests\autoupdate-regression.ps1 -ScoopHome (Resolve-Path .\scoop_core)
.\bin\test-autoupdate.ps1 -ScoopHome (Resolve-Path .\scoop_core)
.\bin\test.ps1
```

`bin/test.ps1` はPesterとBuildHelpersを要求し、リポジトリのPesterテストを実行する。`Scoop-Bucket.Tests.ps1` はScoop側の `Import-Bucket-Tests.ps1` を読み込む。

## CI/CDワークフロー

### CI ([../.github/workflows/ci.yml](../.github/workflows/ci.yml))

トリガーは次のとおり。

- `main` または `master` へのpush
- すべてのPull Request
- `workflow_dispatch`
- `Hermes Light` の `workflow_run` 完了

`workflow_run` のジョブは、元のrunが同じリポジトリの `main` で成功した場合だけ実行する。通常のジョブは `windows-latest` の `powershell` と `pwsh` のmatrixで、次を順に実行する。

| テスト | 実際の処理 |
| --- | --- |
| `tests/distribution-versions.ps1` | Scoopの `Compare-Version` で `<upstream>-rN` の更新順・逆順・同値を確認する。 |
| `bin/test.ps1` | Pesterをリポジトリ全体へ適用し、ルートの `Scoop-Bucket.Tests.ps1` 経由でScoop標準テストを読み込む。 |

### Autoupdate validation ([../.github/workflows/autoupdate.yml](../.github/workflows/autoupdate.yml))

トリガーは次のとおり。

- `main` または `master` へのpush
- すべてのPull Request
- `workflow_dispatch`
- `Excavator` または `Hermes Light` の `workflow_run` 完了
- UTC 06:43の毎日スケジュール（cron: `43 6 * * *`）

`workflow_run` のジョブは、元のrunが同じリポジトリの `main` で成功した場合だけ実行する。Windows PowerShellで次を実行する。

| テスト | 実際の処理 |
| --- | --- |
| `tests/autoupdate-regression.ps1` | 一時HTTP fixtureと使い捨てmanifestで、checkver/autoupdateの受理・拒否ケース、URL・hash・extract_dir、元ファイル非変更を回帰検証する。 |
| `bin/test-autoupdate.ps1` | manifestのコピーに実際のScoop checkver/autoupdateを1回適用し、更新後のURLをダウンロード、hashとextract_dirを検証する。アプリのinstallやhookは実行しない。 |

### README ([../.github/workflows/readme.yml](../.github/workflows/readme.yml))

検証ジョブのトリガーは次のとおり。

- `main` へのpushで、次のpathのいずれかが変更された場合：`bucket/**`、`README.md`、`scripts/update-readme.py`、`tests/test_readme.py`、`.github/workflows/readme.yml`
- Pull Requestで同じpathのいずれかが変更された場合
- `workflow_dispatch`
- `Excavator` の `workflow_run` 完了

`workflow_run` の検証ジョブは、元のrunが同じリポジトリの `main` なら実行する（workflowの成功・失敗は条件に含まれない）。検証ジョブは次を実行する。

```bash
python3 -m unittest discover -s tests -p test_readme.py -v
python3 scripts/update-readme.py
python3 scripts/update-readme.py --check
```

更新ジョブはPull Requestではなく、`main` を指すpush・手動実行・上記の `Excavator` workflow_runでだけ動き、write権限でREADMEをcommit・pushする。`workflow_run` ではpath filterはなく、ジョブの条件は同じリポジトリの `main` だけである。

Hermes Lightのpublisherも `scripts/update-readme.py` と `--check` を実行し、manifestとREADMEを同じcommitで `main` に書き戻す。README workflowの `workflow_run` 元はHermes Lightではない。

### Excavator ([../.github/workflows/excavator.yml](../.github/workflows/excavator.yml))

手動実行と、UTCの4時間ごとのcron（`20 */4 * * *`、各時刻の20分）で起動する。Windows runnerで `ScoopInstaller/GithubActions` を実行し、contents write権限を持つ。

### Hermes Light ([../.github/workflows/hermes-light.yml](../.github/workflows/hermes-light.yml))

トリガーは次のとおり。

- UTCの4時間ごとのcron（`23 */4 * * *`、各時刻の23分）
- `workflow_dispatch`（`revision`入力あり）
- Pull Requestで次のpathのいずれかが変更された場合：
  - `.github/workflows/hermes-light.yml`
  - `scripts/*hermes-light*`
  - `scripts/distribution.py`
  - `tests/test_distribution.py`
  - `tests/test_hermes_light*.py`

ジョブは次のように分離される。

| ジョブ | 実際の処理 | runner |
| --- | --- | --- |
| `plan` | `test_hermes_light*.py` と `test_distribution.py` のunittest、`scripts/hermes-light.py plan` | Ubuntu |
| `build` | Light variantをビルドし、`scripts/smoke-hermes-light.cjs` のsmokeを実行してartifactを作成 | Windows 2025 |
| `publish` | 公開済みassetを再検証し、Release公開後にmanifest・READMEを `main` へ書き戻す `scripts/hermes-light.py publish` | Ubuntu |

`publish` は、`vars.HERMES_LIGHT_RELEASE_ENABLED == 'true'`、`schedule`または`workflow_dispatch`、`refs/heads/main` のすべてを満たす場合だけ実行する。PRではpreviewのplan/buildまでで、Release公開と書き戻しは行わない。artifact名は `hermes-light-windows-x64`、保持期間は14日である。

### その他の自動化

- [Pull Requests](../.github/workflows/pull_request.yml): Pull Requestのopenedと、`/verify` を含むissue commentのcreatedを受け、WindowsでScoopのGitHub Actionを実行する。
- [Issues](../.github/workflows/issues.yml): issueのopenedまたは `verify` label付きlabeledを受け、WindowsでScoopのGitHub Actionを実行する。

## CIで検証される範囲

| 項目 | workflow | 条件・内容 |
| --- | --- | --- |
| Scoopのmanifestテスト | CI | WindowsのPowerShell / pwsh matrixでPesterを実行する。 |
| 配布改訂順 | CI | `Compare-Version` で `<upstream>-rN` の数値順を確認する。 |
| autoupdate回帰 | Autoupdate validation | 一時fixtureでPowerShellの回帰ケースを実行する。 |
| live autoupdate | Autoupdate validation | 実URLを取得し、hashとextract_dirを確認する。 |
| READMEテスト・生成 | README | Python unittest、生成、`--check`を実行する。 |
| Hermes Lightのplan/build | Hermes Light | Pythonテスト、Ubuntuのplan、Windows build/smokeを実行する。 |
| Release公開・main書き戻し | Hermes Light | 公開ゲートを満たしたスケジュール・手動のmain実行だけで実行する。 |

## マージ前後の扱いと未確認事項

PRでは、CIとAutoupdate validationはPRイベントで検証する。READMEは指定path変更時だけ検証し、Hermes Lightは上記のpath変更時だけpreviewのplan（build対象ならbuild）を実行する。

`HERMES_LIGHT_RELEASE_ENABLED` は未設定である。このPRの検証では、Hermes Lightのpublish、publishによる `main` のmanifest・README書き戻し、publish成功後のCI/Autoupdate `workflow_run` follow-upはいずれも未実行である。これらはPRマージ前には検証できない。

mainへのマージ後は、main push、スケジュール、手動実行、各workflowのpath条件に従って再検証される。Hermes Light完了後のCIとAutoupdate validationの `workflow_run` は、同じリポジトリのmainで成功したrunだけを対象にする。READMEの `workflow_run` 元はExcavatorだけである。

Windows上のScoop実インストール、実Release公開、実gateway接続、認証移行、公開後のmain書き戻しは、このローカル手順やPR previewの範囲外である。

## 関連リンク

- [配布ルール](distribution-policy.md)
- [AGENTS.md](../AGENTS.md)
