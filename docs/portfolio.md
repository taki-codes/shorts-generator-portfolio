# 設計と検証の読みどころ

AIへ編集案作成を依頼しやすいJSON形式と、Python・FFmpegによる再現可能な動画生成を組み合わせる開発例です。自動のゲーム内容理解や、自動での公開投稿とは区別しています。

## コードを読む順番

1. [入力スキーマ](schema.md): 元動画時刻、完成動画時刻、字幕原文と編集案。
2. [core.py](../owshort/core.py): 入力検証、フレーム単位の時間管理、音声・映像の合成、manifest。
3. [remotion.py](../owshort/remotion.py): 指示した字幕だけを外部レンダーへ渡す境界。
4. [投稿処理](../owshort/posting.py) / [YouTube連携](../owshort/youtube.py): 対象・公開範囲・処理状態の確認。
5. [メディア統合テスト](../tests/test_workflow.py): 合成素材と模擬VOICEVOXで確認する経路。

編集判断をJSONに残すことで、同じ素材と設定から再生成でき、変更理由も追えます。自然文からの編集判断と、編集案を検証して実行する処理を分担しています。元動画、設定、ツールの版、出力ハッシュを保存しますが、外部素材の権利や編集判断の正しさを自動保証する機能はありません。

## 再現できる確認

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

2026年11月8日、Windows / Python 3.13.1 / FFmpeg 9.0.2で通常の16テストが成功しました。FFmpegでの実ファイル生成、音声のキャッシュ、プレビュー・final書き出し、時刻検証、XMLの参照素材を含みます。VOICEVOXは模擬HTTPサーバーでの契約検証です。

`OWSHORT_SAMPLE_DEST` に新しい出力先を指定すると、統合テストの合成サンプルを保存できます。[既存のサンプル概要](../examples/demo-output/synthetic-summary.json)は、実在のゲーム映像や投稿成果を示すものではありません。

Remotionの共通テストはGit対象外の個別ジョブから独立させました。既存ジョブ専用の確認は、そのファイルが存在するときだけ実行します。今回の環境ではRemotionのNode処理が完了せず、任意の実レンダーテストを中断しました。通常の16テストの成功には含めていません。過去の実機記録は [Remotion資料](remotion.md) を参照してください。

実VOICEVOX音声の聞き取り、Premiereでの再編集、OAuth・実投稿は今回の確認対象外です。
