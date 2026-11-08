# 入力・編集案の形式

字幕ごとにRemotionを使う任意指定（renderer/remotion）は [remotion.md](remotion.md) を参照。指定しない字幕は従来どおり。

UTF-8のJSON。相対パスは project.json の親フォルダー基準。元動画・referenceはローカルファイル。
source と参考動画を混ぜない。参考は分析のみ。plan 内の in/out/focus は元動画基準、comments/sfx の start/end は完成動画基準。

project.json の例（`jobs/first/` に配置）:

```json
{
  "schema_version": 1,
  "source": "C:/Videos/ow-clip.mp4",
  "preferences": "../../config/preferences.json",
  "references": [{"file":"C:/Videos/reference.mp4","role":"reference"}],
  "comments": [
    {"id":"c1","text":"ヒール来ると思ったのに","mode":"voice_subtitle"},
    {"id":"c2","text":"そっち行くんかい！","mode":"subtitle"},
    {"id":"c3","text":"耐えられる？……無理でした","mode":"voice_subtitle"}
  ],
  "voicevox": {"speaker_id":null,"speed":1.05,"pre_pause":0.05,"post_pause":0.1},
  "audio_credits": [],
  "metadata": {"title":"映像を見て作成するタイトル","description":"映像に合わせた説明","hashtags":["#Overwatch","#オーバーウォッチ","#Shorts"]}
}
```

speaker_id=null は未設定。`speakers` の結果から実在するスタイルのIDを選ぶ。`voice_settings` を各コメントに追加すると話速等を個別上書きできる。対応しているエンジンで `pause_scale` を指定すると句読点の間を調整できる。細かな無音区間は別コメント＋時刻に分けて管理する。

生成済み音声はコメントに `voice_file` と `voice_transcript` を追加する。例えば:

```json
{"id":"c1","text":"ヒール来ると思ったのに","mode":"voice_subtitle","voice_file":"audio/c1.wav","voice_transcript":"ヒール来ると思ったのに"}
```

voice_transcript は字幕と完全一致させる。これは入力の整合性確認であり、実音声の文字起こしではない。試聴で内容を確認する。提供音声のクレジットが必要なら audio_credits に追加する。

発音用の表記を変える場合:

```json
{"id":"c1","text":"ヒール来ると思ったのに","mode":"voice_subtitle","pronunciation_text":"ヒールくると思ったのに","pronunciation_reason":"来るをクルと発音させる"}
```

字幕の表示文面は変えない。意味・語彙を変えたい場合は発音の例外で扱わず、言い換え提案として管理する。

指定位置は requested_x/requested_y（画面に対する0..1の字幕中心）、指定時間は requested_start/requested_end（完成動画秒）。元動画の時刻指定はCodexがカット後の出力時刻へ変換し、対応表をproposal.mdに残す。

plan.json の例。これは説明用の時刻であり、あなたの動画を分析した編集案ではない。

```json
{
  "schema_version":1,
  "segments":[
    {"kind":"play","in":0.5,"out":3.0,"speed":1,"reason":"状況とフリを残す"},
    {"kind":"play","in":3.0,"out":5.0,"speed":1,"focus":{"x":0.35,"y":0.3,"w":0.3,"h":0.3},"reason":"見せ場を追加パネルで強調"},
    {"kind":"freeze","in":5.0,"duration":0.4,"reason":"オチの前に間を残す"},
    {"kind":"play","in":5.0,"out":8.0,"speed":1,"reason":"結果を見せる"},
    {"kind":"play","in":6.5,"out":8.0,"speed":1,"reason":"オチを短くリプレイ"}
  ],
  "comments":[
    {"id":"c1","start":0.2,"end":2.5,"x":0.46,"y":0.76},
    {"id":"c2","start":2.5,"end":4.5},
    {"id":"c3","start":4.9,"end":8.5}
  ],
  "sfx":[],
  "proposed_comments":[]
}
```

- playはin以上out未満。速度は0.5..2。音声もatempoで同じ速度にする。
- freezeはinの画像をduration秒維持。元ゲーム音は無音にする。必要なら別音声をsfxに配置。
- リプレイは同じ元動画範囲を再度playに入れる。理由で意図を明示する。
- focusは元動画の正規化座標。全体表示を維持し、追加の拡大パネルへROIを出す。キーフレーム追従はv0.1未実装。
- sfxは `{"file":"audio/pop.wav","start":4.6,"gain_db":-12,"reason":"オチの着地"}` のように追加。素材を同梱していない。自作または利用可能な効果音を用意する。
- 字幕と読み上げはstartを共有。音声が字幕のendを超える場合はエラー。字幕時間を延ばすかVOICEVOXの話速を調整して再生成。
- 時刻は30/60fpsのフレームへ丸める。各クリップの累積フレーム数から出力時間を計算する。
- 原文の変更は proposed_comments に提案。採用時のみ plan のコメントに display_text/change_reason/change_accepted=true を追加。
- 9:16、SDR、1080×1920、30/60fpsに限定した初期実装。HDRと回転メタデータがある素材は明示的な前処理が必要。
- JSONの編集で後から再生成可能。字幕の長文を勝手に省略しない。画面外の字幕は書き出しを止める。

config/preferences.json の caption はサイズ・色・輪郭・行数・初期位置。layout は全体と拡大パネルの矩形。
初期字幕位置は各サービスのUIを避ける目安で、永続的な安全領域の保証ではない。端末のプレビューで確認する。
