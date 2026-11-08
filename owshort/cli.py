import argparse
import json
from pathlib import Path
from . import core


def main():
    parser = argparse.ArgumentParser(description="Reviewable local short-video pipeline")
    sub = parser.add_subparsers(dest="command",required=True)
    d = sub.add_parser("doctor"); d.add_argument("--out",default="diagnostics.json")
    for name in ("analyze","tts","validate","render"):
        p = sub.add_parser(name); p.add_argument("project")
        if name == "analyze":
            p.add_argument("--interval",type=float,default=1)
        elif name == "tts":
            p.add_argument("--plan")
        else:
            p.add_argument("plan")
        if name == "render":
            p.add_argument("--stage",choices=["preview","final"],default="preview")
    p = sub.add_parser("speakers"); p.add_argument("--preferences",default="config/preferences.json")
    p = sub.add_parser("feedback"); p.add_argument("key"); p.add_argument("value",help="JSON value, e.g. 84, -14, true")
    p.add_argument("--note",required=True); p.add_argument("--preferences",default="config/preferences.json")
    p = sub.add_parser("youtube-auth"); p.add_argument("client_secrets"); p.add_argument("--profile",required=True)
    p = sub.add_parser("youtube-channels"); p.add_argument("--profile",required=True)
    p = sub.add_parser("youtube-upload"); p.add_argument("build"); p.add_argument("--profile",required=True); p.add_argument("--channel",required=True)
    p.add_argument("--made-for-kids",required=True,choices=["true","false"])
    p = sub.add_parser("youtube-status"); p.add_argument("receipt"); p.add_argument("--profile",required=True)
    p = sub.add_parser("tiktok-handoff"); p.add_argument("build"); p.add_argument("--username",required=True)
    p.add_argument("--result-type",required=True,choices=["draft","self_only"])
    a = parser.parse_args()
    try:
        if a.command == "doctor":
            report = core.doctor(); core.write_json(a.out,report); print(json.dumps(report,ensure_ascii=False,indent=2))
        elif a.command == "analyze":
            print(core.analyze(a.project,a.interval))
        elif a.command == "speakers":
            base = core.voice_base(core.read_json(a.preferences))
            speakers = json.loads(core.http_json(base+"/speakers"))
            for s in speakers:
                for style in s["styles"]:
                    print(f"{style['id']}\t{s['name']} / {style['name']}")
        elif a.command == "tts":
            print(json.dumps(core.synthesize(a.project,a.plan),ensure_ascii=False,indent=2))
        elif a.command == "validate":
            ctx = core.validate(a.project,a.plan)
            print(json.dumps({"duration":ctx["duration"],"warnings":ctx["warnings"],"status":"VALIDATED"},ensure_ascii=False))
        elif a.command == "render":
            print(core.render(a.project,a.plan,a.stage))
        elif a.command == "feedback":
            core.feedback(a.preferences,a.key,json.loads(a.value),a.note); print("Preference and history saved")
        elif a.command.startswith("youtube-"):
            from . import youtube
            if a.command == "youtube-auth":
                youtube.authorize(a.client_secrets,a.profile); print("OAuth token saved locally (Windows DPAPI)")
            elif a.command == "youtube-channels":
                print(json.dumps(youtube.channels(a.profile),ensure_ascii=False,indent=2))
            elif a.command == "youtube-upload":
                print(json.dumps(youtube.upload(a.build,a.profile,a.channel,a.made_for_kids=="true"),ensure_ascii=False,indent=2))
            else:
                print(json.dumps(youtube.status(a.receipt,a.profile),ensure_ascii=False,indent=2))
        elif a.command == "tiktok-handoff":
            from .posting import tiktok_handoff
            print(tiktok_handoff(a.build,a.username,a.result_type))
    except (core.WorkflowError, KeyError, ValueError, FileNotFoundError) as e:
        parser.exit(2,f"Error: {e}\n")


if __name__ == "__main__":
    main()
