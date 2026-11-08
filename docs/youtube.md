# YouTubeの初期連携: 非公開のみ

本体のアップロードコードは実装したが、OAuth・実チャンネル・実アップロードは未検証。
初回はユーザーがGoogle Cloudとブラウザ認証を設定する。パスワードをこのチャットに送らない。

1. https://console.cloud.google.com/ でプロジェクトを作成し、YouTube Data API v3を有効にする。
2. OAuth同意画面を設定する。テスト用なら自分のGoogleアカウントをテストユーザーに登録。
3. OAuthクライアントは「デスクトップアプリ」で作成する。JSONをキットの secrets/client_secret.json へ保存。
4. `bootstrap.ps1 -YouTube` で追加依存を導入する。
5. 以下でブラウザを開いて認証。対象YouTubeチャンネル/Brandアカウントを正しく選ぶ。

```powershell
.\.venv\Scripts\python.exe -m owshort.cli youtube-auth secrets/client_secret.json --profile main
.\.venv\Scripts\python.exe -m owshort.cli youtube-channels --profile main
```

一覧のIDを指定して非公開アップロードする（BUILD_PATHとCHANNEL_IDは実際の値へ置換）。子供向け設定は自分の動画に合わせてtrue/falseを指定する。

```powershell
.\.venv\Scripts\python.exe -m owshort.cli youtube-upload "BUILD_PATH" --profile main --channel "CHANNEL_ID" --made-for-kids false
.\.venv\Scripts\python.exe -m owshort.cli youtube-status "BUILD_PATH/youtube-receipt.json" --profile main
```

コードは対象channel IDとOAuthで得られるチャンネルを照合し、常にprivateで送信する。
タイトル・説明・ハッシュタグ・VOICEVOXクレジットを登録する。合成音声の個別規約が要求するクレジットは必要に応じて追加。
OAuthトークンはWindowsユーザーに紐づくDPAPI暗号化でLOCALAPPDATAへ保存する。認証情報・ブラウザプロフィールは成果物に含めない。
Windows DPAPI処理はこのLinux環境では実行できないため、PCで認証→復号→API読取を検証する必要がある。

| state | 意味 |
|---|---|
| UPLOADING | バイトの転送中 |
| UPLOADED_PROCESSING | video IDを取得したが処理完了を未確認 |
| COMPLETE_PRIVATE | 処理完了とprivate、所有チャンネルをAPIで確認 |
| FAILED | APIが失敗/拒否/処理終了を返した |
| CHECK_REQUIRED | 中断等でID不明。Studioで重複を確認してから再試行 |
| PRIVACY_MISMATCH / ACCOUNT_MISMATCH | 期待した公開範囲/チャンネルと不一致 |
| NOT_FOUND_OR_NOT_ACCESSIBLE | 未検出またはアクセス権不足 |

処理中なら後からyoutube-statusを実行する。statusコマンドは再アップロードしない。
同じ動画ハッシュ・チャンネルのアップロード履歴を保存し、再実行による二重投稿を避ける。ID不明の中断は自動で新規投稿せず、確認を要求する。
転送は同一プロセス内でresumable uploadと一時エラーの再試行を使う。PC再起動後の転送再開は未実装。

Shorts専用のアップロードエンドポイントは使わない。縦/正方形で3分以内の動画は現在のYouTube仕様上Shortsの対象になるが、APIの成功だけではShorts分類を確認できない。Studioで分類を確認する。
未確認APIプロジェクトは非公開に制限されるため、将来の公開・予約連携にはプロジェクトの審査状況も確認する。
公開/予約投稿のCLIは初期版では未実装。ユーザーの具体的な投稿日時と公開範囲が決まった段階で拡張する。
同意画面がTestingの場合などはトークンの有効期間が制限され得る。失効したらyoutube-authを再実行する。

公式資料:
- https://developers.google.com/youtube/v3/docs/videos/insert
- https://developers.google.com/youtube/v3/docs/videos
- https://developers.google.com/youtube/v3/guides/uploading_a_video
- https://developers.google.com/identity/protocols/oauth2/native-app
- https://support.google.com/youtube/answer/15424877?hl=ja
