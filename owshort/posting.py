"""Produce browser handoff with honest states; never pretend a generated packet was uploaded."""
import re
from pathlib import Path
from .core import WorkflowError,write_json,read_json,now
from .youtube import final_build


def tiktok_handoff(build,username,result_type):
    build,manifest,video = final_build(build)
    username = username.lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_.]{2,24}",username):
        raise WorkflowError("Specify the target TikTok username, not its display name")
    meta = read_json(build/"metadata.json")
    if len(meta["tiktok_caption"].encode("utf-16-le"))//2 > 2200:
        raise WorkflowError("TikTok caption exceeds conservative 2200 UTF-16 unit limit; edit metadata")
    write_json(build/"tiktok-receipt.json",{"platform":"tiktok","target_username":username,"requested_result_type":result_type,
        "requested_privacy":"SELF_ONLY" if result_type=="self_only" else None,"state":"HANDOFF_READY_NOT_UPLOADED",
        "created_at":now(),"video_sha256":manifest["video_sha256"],"video_file":str(video),"confirmation_url":None,
        "verification_source":None,"metadata_registered":False,"processing_complete":False})
    draft = result_type == "draft"
    text = f"""# TikTokブラウザ操作の引き継ぎ

対象アカウント: @{username}
希望結果: {'下書き（未投稿）' if draft else '自分のみ公開（投稿済み）'}
動画: {video}
文面: upload-text.txt
現時点の状態: HANDOFF_READY_NOT_UPLOADED。まだサイトに送信していません。

ローカルCodex＋設定済みブラウザMCPで操作する場合:
1. https://www.tiktok.com/tiktokstudio/upload を開き、実際の画面を調べる。
2. ログインはユーザーに任せる。ユーザー名を画面で照合し、違うアカウントには送らない。
3. file upload 機能で指定動画を選択。upload-text.txt の文面を編集可能な状態で登録。
4. 長さ・表示・音声・クレジット・必要な申告欄を実画面に合わせて確認。
5. {'下書き保存機能が表示される場合のみ保存。なければ停止して「この画面では下書き不可」と報告。' if draft else '公開範囲で「自分のみ」を選択して、現在の設定と文面を照合し投稿。'}
6. {'下書き一覧で存在を確認。投稿済みや自分のみ公開と扱わない。' if draft else '処理完了後、一覧または詳細画面で動画と「自分のみ」を照合。'}
7. 実際に観測した状態だけ tiktok-receipt.json に記録。画面の証拠と確認先を残す。

状態値: UPLOADING / PROCESSING / DRAFT_SAVED / POSTED_SELF_ONLY / FAILED / NEEDS_USER_ACTION。
receipt の verification_source に observed_browser と証拠パス、confirmation_url に確認先を記録。
metadata_registered=true は文面をサイトで確認できた場合だけ。processing_complete=true は完了を確認できた場合だけ。
ログイン・CAPTCHAが操作を止めたらユーザー操作へ引き継ぎ、突破しようとしない。
ボタン名やDOMは事前に保証しない。固定セレクタの無確認連打は禁止。

初期実装は引き継ぎファイルの生成まで。ブラウザ接続・実アカウント・サイト操作は未検証。
Direct Post API は個人専用ツールの採用候補から除外。Upload API もアプリ承認等が未設定。
APIの inbox delivery はスマホ通知から編集を続ける方式で、キャプション登録済みの下書きとは異なる。
"""
    target = build/"tiktok-browser-task.md"
    target.write_text(text,encoding="utf-8")
    return target
