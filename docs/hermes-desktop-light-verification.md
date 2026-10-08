# Hermes Desktop Light 検証

共通の[配布ルール](distribution-policy.md)と[検証記録](distribution-validation.md)を前提に、Hermes Desktop Light固有の上流・Light・gateway契約と、実行済みCIの結果を記録する。

## Hermes Desktop Light固有の契約

- 安定版として扱う上流タグは、上流の`STABLE_TAG_RE`と同じ`vX.Y.Z`形式のSemVerだけとする。Draft・Prerelease・canary・歴史的CalVerは対象外である。
- 上流のstable-release toolingが作るclaimと、公開時の安定タグ本文に入るreceiptを検証する。Release状態、タグから解決したcommit、claimのversion・commit・tag情報が一致しないものはadmissionしない。
- sourceのLight identityと管理されたLight builderの対応ファイルを検査し、非対応や必要ファイルのないcommitは理由を記録してskipする。API障害や権限エラーはskipと混同せず失敗させる。
- 配布物はリモート専用のLight構成で、既存のHermes gatewayへの接続を必要とする。起動smokeだけではgateway接続、認証・接続設定の移行、Lightのローカル実行可否を証明しない。これらはWindowsで別途受入確認する。

## 個別検証の入口

共通のローカル手順は[検証手順](verification.md)から実行する。Hermes Desktop Light固有のNode.js smokeスクリプトは、次で構文を確認する。

```bash
node --check scripts/smoke-hermes-desktop-light.cjs
```

PythonのHermes Desktop Light・配布契約テストは、共通の`unittest discover`に加えて、必要なら次のように個別実行できる。

```bash
python3 -m unittest discover -s tests -p 'test_hermes_desktop_light*.py' -v
python3 -m unittest discover -s tests -p 'test_distribution.py' -v
```

## Hermes Desktop Light workflow

[`hermes-desktop-light.yml`](../.github/workflows/hermes-desktop-light.yml)は、UTCの4時間ごとのschedule、`workflow_dispatch`（`revision`入力）、および関連ファイルを変更したPull Requestで起動する。`plan`はUbuntuで個別テストと`hermes-desktop-light.py plan`をread-only実行し、Light対応と対象を決める。対象がある場合だけ`build`がWindows runnerでビルド・smokeを実行し、`hermes-desktop-light-windows-x64` artifactを作る。

`publish`はリポジトリ変数`HERMES_DESKTOP_LIGHT_RELEASE_ENABLED == 'true'`、scheduleまたは`workflow_dispatch`、`refs/heads/main`、build対象のすべてを満たす場合だけ実行する。Pull Requestではpublishを実行しない。公開済みassetの再検証とRelease公開、manifest・READMEのmain書き戻しのゲートは、未確認事項とともにこの文書へ記録する。

### 改訂

通常の安定版追従は`r1`。公開済みの同じ上流版を修正する場合、信頼済みmainの手動workflowの`revision`を増やす。対象はその時点の最新対応安定版であり、過去上流版を指定してのバックポートビルドは現在の自動化の対象外である。公開ゲートは既定で無効のままとする。gateway接続・認証移行などの阻害条件は、改訂番号を増やしただけでは解消したと扱わない。

## 実Windows CI: run 37738844817

[Hermes Desktop Light run 37738844817](https://github.com/takano536/scoop-bucket/actions/runs/37738844817)を、PR #8のhead `90b05923687d846397fbab287b91b51d9ab60f81`に対する`pull_request`イベントで実行した。`plan`・`build`・`acceptance`はsuccess、`publish`はskippedだった。

Actionsのcheckoutログで、ビルドjobが実際にcheckoutしたbucketのPR merge refは`3acdfc472b635fac6a382c51c1b5e03e6963dc10`（`90b05923687d846397fbab287b91b51d9ab60f81`を`1bccbc5ec3f093348c2e13b1fd09b32a8ecae91e`へmergeしたcommit）である。したがって、runのhead SHAと、PR検証用のmerge refを区別して記録する。上流checkoutは`NousResearch/hermes-agent@a3ed4a173070e981332e4d879ff6cc8b9efd57ab`だった。

### 成果物とprovenance

- build artifact [`hermes-desktop-light-windows-x64`](https://github.com/takano536/scoop-bucket/actions/runs/37738844817/artifacts/11533625401): **170,080,519 B**。
- acceptance artifact [`hermes-desktop-light-windows-acceptance`](https://github.com/takano536/scoop-bucket/actions/runs/37738844817/artifacts/11532849103): **15,753 B**。
- 上流: `NousResearch/hermes-agent@a3ed4a173070e981332e4d879ff6cc8b9efd57ab`。
- acceptanceのgateway preflightが報告した上流アプリversion: `0.21.5`。
- provenanceの配布version: `preview-a3ed4a1`。acceptanceの`bucketPackageVersion`は`preview`であり、安定版versionではない。
- ZIP: `hermes-desktop-light-preview-a3ed4a1-windows-x64.zip`。
- ZIP SHA256: `cd577d5789cbaefecf4750cf580ea940e86ff659bba0953470fb9d4779780c3c`。
- `provenance.json`の`run`は上記run URL、`payload`は`light`、`updateMechanism`は`external`、実行ファイルはupstream commitのpreview executable、署名は`unsigned unofficial build`である。provenanceのSHA256とacceptanceの`artifactSha256`は一致する。
- provenanceのsmoke記録は、native launchを2回実行し、rendererのloadとlocalStorage保持を確認したものだった。これはPR用preview artifactであり、GitHub Releasesへの公開やmanifest登録は行っていない。

### acceptance artifactの内容と実際に確認したこと

acceptance artifactには`acceptance.json`、`before.json`、`after.json`、`scoop-update-evidence.json`、`runtime-evidence.json`、gateway/HTTPログが含まれ、`acceptance.json`のstatusは`passed`だった。test-onlyの`hermes-desktop-light-acceptance.json`を使ったdisposable local bucketで、次を確認した。

- Scoopのbefore versionは`0.0.0-test-before-a3ed4a1`、after versionは`0.0.1-test-after-a3ed4a1`。manifest/install version、resolved `current` target、Start Menu shortcutのresolved targetを読み戻し、版切替assertionとno-op拒否がpassedになった。afterの`current`とshortcutはafter versionの実行ファイルを指した。
- Scoop update後にStart Menuの`.lnk`経由で起動し、アプリとshortcutをuninstallで削除した。`HERMES_HOME`/Desktop user-dataは残った。
- before/afterともremote modeで、同じlocalhost gatewayへの接続設定とtokenSetを保持し、token自体はexportしなかった。after側ではpreload bridge経由のauthenticated `session.list` WebSocket RPCを実行した。別のdirect Node probeでは`/api/sessions?limit=1`の認証済みHTTPが200、誤secretが401だった。
- gatewayは上流の同じsource commitで`hermes serve --host 127.0.0.1 --port <ephemeral> --skip-build`として起動し、provider credentialは与えなかった。job内で生成したdashboard session tokenはmaskされた。
- Light ZIPに`resources/agent-payload`はなく、local backend probeは`bootstrap-needed`を返した。bootstrap/local agentは起動していない。画面にlocal-installのaffordanceがあっても、同梱local backendの実行を意味しない。
- updaterは`external`、checkは`reason=commit-build`、applyはunsupportedとして拒否され、app treeは不変だった。
- `runtime-evidence.json`はインストール済みapp treeの20ファイルを`dumpbin /DEPENDENTS`で検査した。runtime import 58件、API set probe 58件が記録され、58件はOS提供側に解決した。VC++ redistributable import、同梱runtime DLL、unparseable、unresolved、missing runtimeはいずれも0件で、`accepted`はtrueだった。

このrunのWindows runnerはGitHub-hosted環境であり、`runtime-evidence.json`の`runnerIsClean`はfalseである。runtime検査の受入結果は、クリーンなWindows consumer machineでのruntime独立性を保証しない。前提とする最小環境はElectronの対応最小環境であるWindows 10+であり、別途クリーン環境での確認が必要である。

### 何を更新検証したか

before/afterは異なるtest-only versionを付けて**同じZIP（同じ名前・同じSHA256）を再インストール**したものだった。これはScoopのupdate path、`current`/shortcut切替、設定・認証保持、uninstallを検証するテストである。異なるupstream commitや異なるバイナリ間のmigrationを行ったものではなく、migrationの成功を主張しない。

## 失敗runの履歴

[run 37714650337](https://github.com/takano536/scoop-bucket/actions/runs/37714650337)は、旧workflowの`pull_request` runで、headは`be274390408caa73f1f79d89b96285b2c5662e9b`だった。`plan`と`build`はsuccess、`acceptance`はfailure（`Run Scoop and remote-gateway acceptance` step）、`publish`はskippedだった。このrunは履歴として保持するが、上記の成功runやruntime受入の証拠とは混同しない。

## PR #8 merge後のmain

PR #8のmerge commitは`2c4f4298160912f53faefd7b40cdc97f42a133f6`。このcommitの後に、workflow `Hermes Desktop Light`をbranch `main`で検索した結果は0件であり、merge後にmain上でHermes Desktop Light workflowが実行されたことは確認できなかった。

一方、同じmain commitに対して次のread-only workflowは成功した。

- [CI run 37740115916](https://github.com/takano536/scoop-bucket/actions/runs/37740115916): `Test (pwsh)`、`Test (powershell)`ともsuccess。
- [Autoupdate validation run 37740115767](https://github.com/takano536/scoop-bucket/actions/runs/37740115767): `validate`がsuccess。

現時点の`main`はstable channelのみを含む。開発channelは別PRのままmainへ未マージのため、この文書ではその機能や挙動を検証済みとは扱わない。

## 未確認事項と配布開始条件

今回のrunはPR用previewであり、次は未確認である。

- 対応安定版でのtag/claim admission、安定版の実ビルド、安定版のScoop version。
- 異なるバイナリ間の実migration。今回確認したのは同じpreview ZIPのtest-only version bumpだけである。
- GitHub Releases公開、manifest/READMEのmain書き戻し、安定版の実アップグレード。
- クリーンなWindows consumer machineでのruntime独立性。
- provider/LLM credentialを使う実運用。

初回manifestは、Light対応の安定版を実際にビルド・受入確認・公開できた後に生成する。main由来のコードを過去安定版の名前で配布しない。公開ゲート`HERMES_DESKTOP_LIGHT_RELEASE_ENABLED`は有効化せず、PRからReleasesへ公開しない。

## 公開ゲート

公開jobは`HERMES_DESKTOP_LIGHT_RELEASE_ENABLED`が`true`、scheduleまたは`workflow_dispatch`、`main`、build対象のすべてを満たす場合だけ実行する。公開前に、対象tagと同梱物のライセンス・著作権表示・第三者通知、名称と非公式配布表示、Windows実行・必要runtime・更新移行・外部サービス接続を再検証する。公開済みassetを上書きせず、manifest・READMEは公開URLからSHA256を再検証した後に書き戻す。

## 配布契約の検証記録

この文書に記録したrunは、PR headとActions checkoutのmerge ref、上流commit、provenance、ZIP SHA256、受入artifactを対応付けている。Actions artifactは一時検証用であり、Scoopの恒久的な配布先ではない。今回のrunではRelease作成、manifest登録、mainへの書き戻しを行っていない。
