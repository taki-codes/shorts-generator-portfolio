# 指定した字幕だけRemotionで作る

通常は従来のPython＋FFmpeg。チャットで「完成動画の3秒あたりの字幕だけRemotionで、跳ねるように作って、それを使って」と指定すれば、Codexが該当コメントだけ下記設定へ変更してレンダーする。Python自体に自然言語を解析する機能を追加したわけではない。チャット指示→Codexが対象を特定・設定/Reactコードを作成→Remotionで透明素材を生成→FFmpegで合成、という流れ。

## 初回セットアップ

キットのremotionフォルダーで `npm.cmd ci --no-audit --no-fund`。Node.jsとローカルChrome/Edgeが必要。既存ブラウザーを自動検出する。別の実行ファイルなら環境変数OWSHORT_REMOTION_BROWSERで指定する。既存ブラウザーが見つからない場合はRemotion標準のブラウザ取得が必要。音声エンジンは変更しない。通常字幕だけのジョブはNode/Remotionを呼ばない。

## plan.jsonのコメント例

これは説明用であり、既存の実案件へは適用していない。

```json
{
  "id": "c1",
  "start": 3.0,
  "end": 5.0,
  "x": 0.5,
  "y": 0.76,
  "renderer": "remotion",
  "remotion": {
    "request": "3秒あたりの字幕だけRemotionで、跳ねて単語ごとに色が変わるように",
    "effect": "bounce-highlight",
    "bounce_height": 45,
    "tokens": [
      {"text": "全部", "start": 0.0, "end": 0.6, "color": "#ff4422"},
      {"text": "受け止める！", "start": 0.6, "end": 2.0, "color": "#ffb52e"}
    ]
  }
}
```

- renderer未指定またはdefaultなら従来処理。remotion.requestはユーザーの指示を保存する欄で、Remotionに自然文を送るAPIではない。
- effectはbounce（登場時に跳ねる）、word-highlight（指定単語を色付け）、bounce-highlight（両方）。tokens省略時は全文が一つの単位になる。
- tokensの時刻は字幕が出始めてからの相対秒。結合したtextは字幕と完全一致。話速や音声の再生成はこの設定では行わない。発音時刻の自動検出は含まない。
- x/yは完成画面に対する字幕中心0..1。previewとfinalの解像度に合わせて字幕素材も生成する。
- 生成物は各build/remotion/の透明ProRes 4444 MOV、リクエストJSON、ハッシュ付き記録、再生用バンドル。mainのmanifestにも使用素材を記録する。
- 字幕表示開始で素材の0フレーム目から再生する。短いループの無条件反復はしない。表示区間の外には残さず、同じ字幕の通常PNG/炎MOVを重ねない。
- SRTと静止PNGも受け渡し用に残す。Premiere XMLは静止PNGの代替なのでRemotionの動きは再現しない。透明MOVを別途読み込めるかはPremiere実機での検証が必要。

## 独自演出

定型以外はCodexがジョブ内（例jobs/<name>/remotion/index.tsx）へReact/Remotionコードを作る。remotion.entry_pointにproject.jsonからの相対パス、remotion.composition_idに登録したCompositionのIDを指定する。追加設定はremotion.propsに記録する。

Compositionにはtext、width、height、fps、durationInFrames、x/y、fontSize、stroke、color、maxWidth、effect、bounceHeightとtokensが渡る。propsの任意フィールドはこの予約フィールドを上書きできない。文字・意味を勝手に変更せず、指定位置に収まる透明な全画面素材を作る。幅/高さ/fps/フレーム数はPython側で出力に合わせる。npmパッケージはキットのremotion/node_modulesから解決する。ジョブ固有の追加import素材は生成バンドルにも残る。

## 実行

通常ジョブは既存CLI `python -m owshort.cli render <project.json> <plan.json> --stage preview` のまま。

ow001-visorは `.venv/Scripts/python.exe jobs/ow001-visor/scripts/build_preview.py --stage preview` を使い、既存の見出しとその他の炎字幕を維持する。新しいbuildへ出力し、確認してからfinalを生成する。

Remotionの透明出力は公式のPNGフレーム＋ProRes 4444＋yuva444p10le方式を使用。
https://www.remotion.dev/docs/transparent-videos

## 2026-10-17の実機検証

Remotion 4.0.536 / React 19.0.0をローカル導入。テスト用映像を用い、透明MOV生成、指定区間だけの表示、通常字幕と混在、通常字幕のみではRemotionを呼ばないことを確認。既存ow001-visorの専用スクリプト経由で見出し・従来の炎字幕・独自React字幕を併用し、1080×1920のfinal出力も成功。既存13テストと追加4テストがそれぞれ成功（別実行）。Premiere実機取り込み・実音声の試聴・外部投稿はこの検証に含まない。

確認用はexamples/remotion-demo/preview.mp4。Remotionのブラウザー制御とプレビュー配信にはlocalhost通信が必要。このCodex実行環境では通常サンドボックスの通信制限により失敗したため、許可されたサンドボックス外の実行で検証した。生成失敗を通常字幕で隠す処理は入れていない。

再検証は環境変数OWSHORT_TEST_REMOTION=1を指定し、`.venv/Scripts/python.exe -m unittest discover -s tests -p test_remotion.py -v`。Windowsの一時フォルダーに制限がある実行環境ではTEMP/TMPをワークスペース内の作業用フォルダーへ指定する。
