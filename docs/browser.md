# TikTok ブラウザ連携（PCで設定・検証が必要）

MicrosoftのPlaywright MCPをローカルCodexに接続し、実際の画面を読みながら操作する。
このキットにはTikTokのDOMやログイン状態を確認した証拠はない。登録スクリプトもWindowsで未実行。
日々変わるボタン名をPythonに固定する方式は初期構成では採用しない。

1. Codex CLIとNode.jsを導入する。
2. `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\connect-browser.ps1` を実行する。既定はEdge。Chromeを使いたいなら末尾に `-Browser chrome`。
3. Codexを再起動し `/mcp` で owshort-browser の接続を確認。
4. 最初はユーザーが専用ブラウザでログイン。普段のブラウザプロフィールをコピーしない。
5. 投稿依頼は final 動画のレビュー後、対象ユーザー名と「下書き」または「自分のみ」を指定する。

設定スクリプトが動かない場合、既存の `~/.codex/config.toml` を上書きせず次のセクションを追加する（パスの YOUR_USER を実際のWindowsユーザーに置換）。

```toml
[mcp_servers.owshort-browser]
command = "npx.cmd"
args = ["-y", "@playwright/mcp@latest", "--browser", "msedge", "--user-data-dir", "C:/Users/YOUR_USER/AppData/Local/OWShortKit/browser-profile"]
```

最初の動作確認後は npmパッケージのバージョンを記録し、そのバージョンに固定する。@latestは初回選定用で、検証したバージョンを示すものではない。

ブラウザMCPは実際の画面にアクセスできる接続で、通常のCodex CLIだけでは利用できない。ChatGPTデスクトップアプリ内のブラウザ機能を使う場合は、そのアプリでローカルファイルを選択できるかを別途確認する。ブラウザ版ChatGPTのクラウドブラウザとPCブラウザは別環境。

利用可能なサイト機能:

| 希望 | 成功の確認 | 未対応の場合 |
|---|---|---|
| 下書き | 下書き一覧で対象動画と文面を確認 | 自分のみ投稿へ勝手に切り替えず、未保存と報告 |
| 自分のみ | 投稿完了・対象動画・公開範囲を確認 | 設定の選択ができなければ停止 |
| 予約 | 実画面が対応していて指定タイムゾーン・日時を確認 | 初期キットで予約を保証しない |

アップロードバーが100%になっただけでは投稿成功としない。PROCESSING/FAILEDを区別し、確認先と画面の証拠をreceiptへ残す。
投稿直前までに実際のサイト上の文面・設定を具体化する。ユーザーの十分な投稿指示が既にある場合は、同じ確認を繰り返さない。

TikTok Direct Post APIについては、自己/チーム管理アカウント専用のutilityを不適切な利用として公式ガイドが列挙しているため、この個人用キットには実装しない。
Upload APIは別機能で video.upload scopeと承認が必要。inbox通知からユーザーが編集・投稿を続ける方式で、文面をセットした通常の下書きとは同一ではない。現在のキットには実装していない。

参考:
- https://github.com/microsoft/playwright-mcp
- https://developers.openai.com/codex/mcp/
- https://developers.tiktok.com/docs/en/content-sharing-guidelines
- https://developers.tiktok.com/docs/en/content-posting-api-reference-upload-video
- https://developers.tiktok.com/docs/en/content-posting-api-reference-get-video-status
