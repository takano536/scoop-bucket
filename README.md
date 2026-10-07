# Scoop Bucket Template

<!-- Uncomment the following line after replacing placeholders -->
<!-- [![Tests](https://github.com/<username>/<bucketname>/actions/workflows/ci.yml/badge.svg)](https://github.com/<username>/<bucketname>/actions/workflows/ci.yml) [![Excavator](https://github.com/<username>/<bucketname>/actions/workflows/excavator.yml/badge.svg)](https://github.com/<username>/<bucketname>/actions/workflows/excavator.yml) -->

Template bucket for [Scoop](https://scoop.sh), the Windows command-line installer.

## How do I use this template?

1. Generate your own copy of this repository with the "Use this template"
   button.
2. Allow all GitHub Actions:
   - Navigate to `Settings` - `Actions` - `General` - `Actions permissions`.
   - Select `Allow all actions and reusable workflows`.
   - Then `Save`.
3. Workflow permissions:
   - Navigate to `Settings` - `Actions` - `General` - `Workflow permissions`.
   - Ensure `Read repository contents and packages permissions` is selected.
   - Then `Save`.
4. Document the bucket in `README.md`.
5. Replace the placeholder repository string in `bin/auto-pr.ps1`.
6. Create new manifests by copying `bucket/app-name.json.template` to
   `bucket/<app-name>.json`.
7. Commit and push changes.
8. If you'd like your bucket to be indexed on `https://scoop.sh`, add the
   topic `scoop-bucket` to your repository.

## How do I install these manifests?

After manifests have been committed and pushed, run the following:

```pwsh
scoop bucket add <bucketname> https://github.com/<username>/<bucketname>
scoop install <bucketname>/<manifestname>
```

## 自動更新の検証

`Autoupdate validation` は、通常のmanifest CIとは別に、Scoop自身の
`checkver.ps1 -ForceUpdate -ThrowError` を使って更新経路を検証します。
PR・default branchへのpush・手動実行・毎日の定期実行・Excavator終了後に実行します。
Excavatorの`GITHUB_TOKEN`によるpushでは通常のpush CIが起動しないため、
`workflow_run`でdefault branchの最新状態を読み直します。

- `checkver` / `autoupdate` / アーキテクチャ別URLの不足を検出。
- 一時コピーのバージョンを保持して、最新版の検出と強制再生成を実行。
  Scoopの実際の`Invoke-AutoUpdate`呼び出し前後に観測処理を挿入した一時スクリプトで、
  対象manifestの更新処理が1回呼ばれ、正常完了したことを必須条件にします。
  差分ゼロでも合格できますが、取得失敗・正規表現不一致で呼ばれなければ失敗します。
  `-Version`は使いません。Scoopの観測箇所が変わった場合も失敗して見逃しを防ぎます。
- 版番号が埋め込まれた固定URL・展開先や、未展開の変数を検出。
- 再生成したURLから実際にダウンロードし、ハッシュを照合。
- `extract_dir`がある場合は7-Zipで展開して、そのディレクトリの存在を確認。
- 既に最新版なら、再生成結果が現在のURL・ハッシュ・展開先と一致することを確認。

ローカルHTTPサーバーを使った回帰テストで正常系と異常系を検証します。
現在版に依存する取得URL、同じ版の再生成、旧版の更新、黙ったスキップなどを
回帰テストで確認します。実際のmanifestが追加されると`bucket/*.json`も全件検証されます。
空bucketは「実manifestの検証未実施」と警告・Summaryに明示します。

### 手動実行

```powershell
gh workflow run autoupdate.yml --repo takano536/scoop-bucket --ref master
```

Scoop・PowerShell 7・7-ZipがあるWindows環境なら、ローカルでも実行できます。

```powershell
.\bin\test-autoupdate.ps1 -ScoopHome (scoop prefix scoop)
```

この検証はmanifest原本を変更せず、インストール・アンインストールのhookも
実行しません。Scoopの更新処理によるダウンロードキャッシュは作成されます。
外部サイト障害も検証失敗になります。将来の配布命名変更、取得元自体が古い版を
返す問題、別製品・別版の正常なファイルを指す問題、インストール・GUI動作、
Excavatorのcommit/push権限は保証しません。
また、複雑な独自hookや複数アーカイブの組合せは個別テストが必要です。

## How do I contribute new manifests?

To make a new manifest contribution, please read the [Contributing
Guide](https://github.com/ScoopInstaller/.github/blob/main/.github/CONTRIBUTING.md)
and [App Manifests](https://github.com/ScoopInstaller/Scoop/wiki/App-Manifests)
wiki page.
