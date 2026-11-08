import argparse
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description="Create a local project from chosen footage")
    p.add_argument("name"); p.add_argument("source",type=Path)
    p.add_argument("--comments",type=Path,help="UTF-8 file; one original comment per line")
    p.add_argument("--reference-file",type=Path); p.add_argument("--reference-url")
    p.add_argument("--brief",type=Path)
    a = p.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}",a.name):
        p.error("Use letters/numbers/-/_ for job name")
    if not a.source.is_file():
        p.error("Source video not found")
    job = ROOT/"jobs"/a.name
    if job.exists():
        p.error("Job already exists; use a new name")
    refs = []
    if a.reference_file:
        if not a.reference_file.is_file():
            p.error("Reference file missing")
        refs.append({"file":str(a.reference_file.resolve()),"role":"reference"})
    if a.reference_url:
        refs.append({"url":a.reference_url,"role":"reference","inspection":"NOT_INSPECTED"})
    lines = a.comments.read_text(encoding="utf-8-sig").splitlines() if a.comments else []
    comments = [{"id":f"c{i}","text":line,"mode":"subtitle"} for i,line in enumerate((x for x in lines if x.strip()),1)]
    project = {"schema_version":1,"source":str(a.source.resolve()),"preferences":"../../config/preferences.json","comments":comments,
               "references":refs,"voicevox":{"speaker_id":None,"speed":1.05,"pre_pause":.05,"post_pause":.1},
               "audio_credits":[],"metadata":{"title":"","description":"","hashtags":["#Overwatch","#オーバーウォッチ","#ゲーム実況"]}}
    job.mkdir(parents=True)
    (job/"project.json").write_text(json.dumps(project,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if a.brief:
        shutil.copy2(a.brief,job/"brief.md")
    else:
        (job/"brief.md").write_text("この動画に指定コメントを入れてください。重要なプレイを残し、フリ・間・オチが伝わる編集にしてください。\n",encoding="utf-8")
    print(job)


if __name__ == "__main__":
    main()
