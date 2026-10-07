# AI エージェント向けの指示

このリポジトリでの開発作業の指示です。

## リポジトリ構成

- `bucket/`: Scoop manifest JSON。
- `scripts/`: Python・PowerShell のビルド、配布、検証スクリプト。
- `tests/`: Python `unittest` と PowerShell の回帰テスト。
- `bin/`: PowerShell の checkver・autoupdate・manifest 検証ユーティリティ。
- `docs/`: 配布ルールと検証手順。
- `deprecated/`: 廃止アプリケーション。
- `.github/workflows/`: GitHub Actions の CI/CD。

## ブランチとPR

- `main` を直接編集せず、必ずレビュー可能なPRを作る。
- 1つのPRは1つの確認可能な変更単位にする。
- 積み上げPRは `gh pr create --base <branch>` で正しいベースを指定する。別PRの変更を `main` ベースのPRへ混ぜない。
- Conventional Commits のタイプは変更内容で選ぶ。
  - `ci:`: CI・workflow・GitHub Actionsだけの変更
  - `docs:`: ドキュメント・CHANGELOGの変更
  - `feat:`: 新しいアプリケーション・機能
  - `fix:`: バグ修正
  - `refactor:`: リファクタリング

## コミットと設定

- モデル選択・認証・個人用 OMP 設定（`.env`を含む）をcommitしない。
- キー・トークン・パスワードをcommitしない。
- バイナリ・ZIPをGitへcommitしない。配布成果物はGitHub Releasesで扱う。
- CIのログ・cache・一時ファイルをcommitしない。

## ビルドと配布

- ビルド成果物の配布ルールは [docs/distribution-policy.md](docs/distribution-policy.md) に従う。
- Release tag は `<app>/v<upstream-version>-r<revision>`。
- Scoop manifest version は `<upstream-version>-r<revision>`。
- ZIP名は `<app>-<upstream-version>-r<revision>-windows-<arch>.zip`。
- 改訂番号の扱い、同一上流版の修正版、再実行時の扱いは [配布ルール](docs/distribution-policy.md) を確認する。

## CIの安全規則

- PRの検証ジョブはread-onlyとし、公開や `main` への書き戻しを行わない。
- Hermes LightのRelease公開と、そのmanifest・README書き戻しは、trusted `main`、明示的な公開ゲート、必要な権限がそろった場合だけ行う。
- Hermes Lightは公開URLから実アセットを取得してSHA256を再検証してからmanifest・READMEを書き戻す。
- Hermes Lightの公開済みアセットを上書きしない。修正版は別Releaseにする。
- 自動化の再実行は冪等にし、重複や黙ったskipを成功扱いにしない。

## 共有ホストのリソース規則

重い処理の前に、次を確認する。

```bash
free -h
cat /proc/swaps
uptime
docker ps
```

- 余裕がある時だけ処理を開始する。
- ビルド、npm install、pip installなどの重い処理は直列化する。
- 他の処理・コンテナを停止しない。
- メモリ・swap・システム設定を変更しない。
- Windowsのビルド・受け入れテストはGitHub Actions runnerを優先する。

## 証拠と検証

- スクリーンショット・ログには安全なフィクションデータだけを使い、実ゲートウェイ情報や認証情報を保存しない。
- localStorageだけの確認を「検証済み」と主張しない。
- 検証手順とCIの実際の結果を分け、未実行の公開・書き戻しを実行済みと記録しない。

## 共著者

実際に貢献したモデルだけを、検証可能な名前・メールアドレスで `Co-authored-by` に記載する。不確かな場合は省略する。

## 関連リンク

- [配布ルール](docs/distribution-policy.md)
- [検証手順](docs/verification.md)
