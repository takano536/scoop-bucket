# bucket-built distributionの検証記録

この文書は、このbucket自身がビルドして配布するアプリに共通する検証記録の形式と
確認範囲を定める。通常の上流バイナリ参照manifestには、bucket-built distribution
向けの公開・改訂・成果物ゲートを適用しない。実行結果、上流commit、artifact、未確認
事項はアプリ固有の契約文書に記録し、この文書ではアプリのversion形式やstable/
admission条件を決めない。

## 共通の検証範囲

bucket-built distributionを変更する場合、アプリ固有の契約に従って次を確認する。

| 検証 | 記録する内容 |
| --- | --- |
| Python・静的回帰テスト | 実行したコマンド、件数、結果、対象アプリ固有の契約テスト |
| manifest・version | `<app>.json`のURL、SHA256、version、改訂順、downgrade拒否 |
| Windows build・受入 | 実行したworkflow/run、上流commit、起動・更新・runtime結果 |
| 公開安全性 | read-only検証、Draft/Releaseのimmutable扱い、公開URLの再検証 |
| README・main書き戻し | 書き戻しを行った場合のcommitとreadback、行わない場合の理由 |

`scripts/distribution.py`の現行helperを使う場合は、数値3要素の上流版と`rN`を採用
するアプリ固有契約であることを確認する。CalVer、4要素版、その他のversion形式は
このhelperの対応範囲外であり、該当アプリのparserと回帰テストを別に記録する。

- [Actions artifact](https://github.com/takano536/scoop-bucket/actions/runs/37641749685/artifacts/11492702573)は一時検証用、保持14日。正式配布先ではない。
- 上流commit: `a3ed4a173070e981332e4d879ff6cc8b9efd57ab`
- ZIP: `hermes-desktop-light-preview-a3ed4a1-windows-x64.zip`
- SHA256: `8ab03e5adc3ce4288d53f04d1382e231f928619b912e2516f9cd296007d2879d`
- 170,392,869 bytes / 1,191 entries。
- ダウンロード後にCRC・hash・Light/external stamp・commit一致・agent非同梱を再確認。
- 二回の実updater IPCはexternal、check supported=false、apply ok=false / commit-build。

アプリ固有文書には、少なくとも次を対応付けて記録する。

- 上流repository、tag/commit、アプリ固有のstable/admission判定結果。
- artifactまたはRelease assetの名前、サイズ、SHA256、provenance。
- `<app>.json`のversion、ダウンロードURL、hashと、上記assetが同じbytesである証拠。
- Actions artifactは一時検証用であり、Scoopの恒久的な配布先ではないこと。

## 未確認事項と阻害条件

PRのread-only CI成功だけでは、実Release公開、Windows上のScoop install/update、
外部サービス接続、認証移行、公開後のmain書き戻しを検証済みとしない。アプリ固有の
契約で未確認の項目、skipと失敗の区別、公開を停止する条件を、その文書に明記する。
公開ゲートを有効化していない場合は、その事実と実行しなかったpublish操作を記録する。
