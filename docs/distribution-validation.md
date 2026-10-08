# 配布ルール変更の検証

対象commit: `3c4b424d8dd16cd77d14842d0e9867d1d9739ed4`

| 検証 | 結果 |
| --- | --- |
| Python回帰テスト | 27件成功。アプリ別タグ・改訂指定・r2/r10の数値順・downgrade拒否・他アプリRelease混在・ページ分割・過去版manifest添付を含む |
| ローカル静的検証 | README生成チェック、Node構文、actionlint、git diff --check成功 |
| [Windows標準CI](https://github.com/takano536/scoop-bucket/actions/runs/37641749710) | Windows PowerShell / PowerShell 7とも成功。Scoop Compare-Versionでr1 < r2 < r10、次の上流版、同版比較を確認 |
| [Autoupdate](https://github.com/takano536/scoop-bucket/actions/runs/37641749687) | 成功 |
| [README](https://github.com/takano536/scoop-bucket/actions/runs/37641749731) | 成功 |
| [Windows Lightビルド・起動smoke](https://github.com/takano536/scoop-bucket/actions/runs/37641749685) | 成功。公開ジョブは実行しない |

## 成果物の対応

- [Actions artifact](https://github.com/takano536/scoop-bucket/actions/runs/37641749685/artifacts/11492702573)は一時検証用、保持14日。正式配布先ではない。
- 上流commit: `a3ed4a173070e981332e4d879ff6cc8b9efd57ab`
- ZIP: `hermes-desktop-light-preview-a3ed4a1-windows-x64.zip`
- SHA256: `8ab03e5adc3ce4288d53f04d1382e231f928619b912e2516f9cd296007d2879d`
- 170,392,869 bytes / 1,191 entries。
- ダウンロード後にCRC・hash・Light/external stamp・commit一致・agent非同梱を再確認。
- 二回の実updater IPCはexternal、check supported=false、apply ok=false / commit-build。

これは固定commitのpreviewであり、安定版の更新所有・gateway接続・認証移行の証明ではない。
対象安定版、ライセンス通知の同梱、実gateway接続、実更新時の設定保持、過去版のScoop導入/固定は未確認。
差分レビューはHermes自身で実施、独立モデルレビューは未実施。
公開実運転はマージと明示的承認後にのみ確認可能。公開ゲート未設定、マージ・実Release作成なし。
