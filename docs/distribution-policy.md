# ビルド済みアプリの配布ルール

[この変更の実行済み検証と未確認事項](distribution-validation.md)

## 名前と正本

- アプリごとにReleaseタグを`<app>/v<upstream>-r<N>`とする。
- Scoop versionとZIP名にも同じ配布改訂番号を含める。初回は`r1`。
- 同じ上流版の修正だけ改訂番号を増やす。通常の再実行では増やさない。
- 上流タグ・commitと配布版を区別する。`r2`でもビルド対象は同じ上流タグであり、上流に存在しないタグを要求しない。
- 公開済みアセットは上書きしない。修正版は別Releaseとし、過去のZIP・provenance・版固定manifestを保持する。
- 各配布版の正本はそのReleaseのアセット。最新版の案内は`main`のアプリ別manifest。リポジトリ全体のLatest Releaseは使用しない。
- ZIPはGitにcommitしない。Actions Artifactsは一時検証用で、Scoopの配布URLには使用しない。

## 複数アプリ

`hermes-agent-light/v0.22.0-r1`と`other-app/v0.22.0-r1`は別Releaseとして共存する。
将来のアプリも`scripts/distribution.py`の識別・比較ルールを利用し、アプリ固有のビルド、ライセンス検査、受け入れ検証、公開ゲートを別に持つ。
ここでの他アプリ名・バージョンは説明例であり、配布物やmanifestを作成するものではない。

公開用workflowのconcurrencyはアプリ単位にする。mainへの書き戻しは最新mainから生成し、競合したら再試行する。force-pushしない。他アプリのmanifestを変更しない。
各アプリのcheckverは公開URL・SHA256検証後に書き戻された自身のmain manifestを参照する。APIのRelease一覧のページ数・他アプリの公開順・未公開上流版には依存しない。

## Hermes Lightの改訂

通常の安定版追従は`r1`。公開済みの同じ上流版を修正する場合、信頼済みmainの手動workflowの`revision`に`2`などを指定する。
対象はその時点の最新対応安定版。過去上流版を指定してのバックポートビルドは現在の自動化の対象外。
改訂番号は正の整数で、先頭ゼロを許可しない。既存manifest以上の版がなければskipし、定期実行が`r2`を`r1`へ戻すことはない。
番号は承認済み修正のために管理者が指定するもので、CI再実行数から自動採番しない。公開ゲート`HERMES_LIGHT_RELEASE_ENABLED`は引き続き既定で無効。

## 公開と過去版

read-onlyのビルド・検証と、上流コードを実行しない公開ジョブを分離する。
DraftにZIP・provenance・その版の`hermes-agent-light.json`を揃え、公開後の実URLからZIPのSHA256を確認してから最新版manifestとREADMEを更新する。
失敗時は最後の正常なmanifestを維持する。公開済みReleaseへの再実行は既存の検証済みバイト列を再利用する。
過去版ZIPはReleaseから直接ダウンロードできる。添付manifestはURLとSHA256を固定するが、checkverは最新版の案内を参照する。Scoopでの過去版導入・固定・ダウングレードは別途実Windows検証が必要で、今回完了とは扱わない。
重大な安全上・権利上の問題では配布停止を優先する。通常の保持方針は危険な成果物を永久に配布する約束ではない。

## 公開前の条件

対象タグと同梱物のライセンス・著作権表示・第三者通知、名称と非公式配布表示を確認する。
各アプリのWindows実行・必要ランタイム・更新移行を検証する。Hermes Lightのgateway接続・認証移行などの既存阻害条件はこのルール変更で解消したとは扱わない。
マージ・公開有効化・実Release作成は別途承認する。
