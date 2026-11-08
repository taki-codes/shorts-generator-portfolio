# Premiere受け渡し: 候補を生成、実機検証は未完了

使用環境はユーザーの訂正を反映して **Windows 11**。最新版の要件はWindows 11 v24H2。
doctorで実際のビルド番号・CPU/GPU/RAMを確認し、要件を満たす場合はCreative Cloudから現行版を導入する。
Windows 11であることだけで要件を満たしたと断定しない。初期のFFmpeg書き出しはPremiereなしでも動く。
OSのアップデートや有料契約はこのキットで自動実行しない。

生成するXMLはFCP7系の xmeml version 5で、FCPXの .fcpxmlではない。以下のファイルをPCで新しく生成してから取り込む。

| ファイル | 中身と制約 |
|---|---|
| review-timeline.xml | カット別の縦配置済み動画、透過字幕PNG、完成ミックス音声。完成動画と比較する確認用 |
| editable-timeline.xml | 同じ映像/字幕、ゲーム音・ナレーション・SEを別トラックに配置。最終のダッキング/ラウドネス処理は再設定が必要 |
| captions.srt | 文面と時刻。Premiereの字幕として取り込んで再配置/デザイン変更するための原本 |
| captions/*-canvas.png | フルキャンバスの透過字幕。タイミングを修正できるが文面・輪郭は焼き込み |
| segments/*.mp4 | カット、速度、静止、部分拡大を適用済み。拡大やカットを大きく変える場合はplanから再生成 |
| game/voice/sfx.wav | タイムライン長の独立音声ステム |
| plan/preferences/project.snapshot.json | 生成した時点の編集案・好み・原文/音声指定 |

Premiere実機での検証手順:

1. バージョンとOS、CPU/GPU情報を記録。
2. 新規プロジェクトへreview-timeline.xmlを「ファイル→読み込み」で取り込む。
3. 全素材オンライン、1080×1920、30/60fps、シーケンス長、カットの位置、静止/リプレイ、字幕の透過・位置、音声の左右と同期を確認。
4. 完成mp4と並べて表示/音を比較。字幕PNGが不適切ならSRTを使い、ネイティブ字幕へ置き換える。
5. .prprojで保存→閉じる→開き直す→短い範囲を書き出し、結果を比較。
6. editable-timeline.xmlも読み込み、独立音声トラックを確認。完成ミックスと一致させるにはバス処理を再設定する。
7. premiere-verification.jsonに、実際のバージョン・成功/失敗・証拠ファイル・不一致を記録する。

Premiereを動かしていないのにVERIFIEDと記録しない。PythonでXMLがパースできることは取り込み成功の証拠にならない。
XMLはローカルの絶対file URLを持つため、buildを別PCへ移したら再リンクが必要。キット内のテスト動画は取り込み互換性の証明ではない。
完全にネイティブなPremiere字幕/エフェクトまで自動生成する連携（UXP等）はv0.1未実装。実機バージョン決定後の追加工程。

公式資料:
- https://helpx.adobe.com/premiere-pro/system-requirements.html
- https://helpx.adobe.com/premiere-pro/using/importing-xml-project-files-final.html
- https://developer.adobe.com/premiere-pro/uxp/
