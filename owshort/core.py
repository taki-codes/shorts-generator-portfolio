from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WorkflowError(RuntimeError):
    pass


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def run(args, cwd=None, log=None):
    # Arguments are passed directly, never interpolated into a shell.
    r = subprocess.run([str(x) for x in args], cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if log:
        Path(log).write_text(r.stderr, encoding="utf-8")
    if r.returncode:
        raise WorkflowError(f"{Path(str(args[0])).name} failed ({r.returncode}): {r.stderr[-5000:]}")
    return r.stdout


def ff(args, **kwargs):
    return run(["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y", "-threads", "2", *args], **kwargs)


def probe(path):
    p = read_probe = json.loads(run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path]))
    videos = [s for s in p["streams"] if s["codec_type"] == "video"]
    audios = [s for s in p["streams"] if s["codec_type"] == "audio"]
    return {"duration":float(p["format"].get("duration", 0)), "video":videos[0] if videos else None,
            "audio":audios[0] if audios else None, "raw":read_probe}


def media_path(base, value):
    if not isinstance(value, str) or not value or re.match(r"https?://", value):
        raise WorkflowError("Local media path required; URL content has not been inspected.")
    path = Path(value).expanduser()
    path = path if path.is_absolute() else Path(base) / path
    path = path.resolve()
    if not path.is_file():
        raise WorkflowError(f"Missing file: {path}")
    return path


def load(project):
    project = Path(project).resolve()
    data = read_json(project)
    prefs = read_json(media_path(project.parent, data.get("preferences", "../../config/preferences.json")))
    return project, data, prefs


def num(value, label, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise WorkflowError(f"{label}: finite number required")
    if low is not None and value < low or high is not None and value > high:
        raise WorkflowError(f"{label}: outside {low}..{high}")
    return value


def frame_time(value, fps):
    return round(value * fps) / fps


def timeline(segments, fps):
    result, cursor = [], 0
    for source in segments:
        s = copy.deepcopy(source)
        if s.get("kind", "play") == "freeze":
            frames = round(s["duration"] * fps)
        else:
            frames = round((s["out"] - s["in"]) / s.get("speed", 1) * fps)
        if frames < 1:
            raise WorkflowError("Segment is shorter than one output frame")
        s.update(start=cursor/fps, end=(cursor+frames)/fps, frames=frames)
        result.append(s)
        cursor += frames
    return result, cursor / fps


def validate(project, plan):
    path, p, pref = load(project)
    plan = read_json(plan) if not isinstance(plan, dict) else copy.deepcopy(plan)
    if p.get("schema_version") != 1 or plan.get("schema_version") != 1:
        raise WorkflowError("schema_version must be 1")
    source = media_path(path.parent, p["source"])
    info = probe(source)
    if not info["video"] or info["duration"] <= 0:
        raise WorkflowError("Source has no video or duration")
    if info["video"].get("color_transfer") in ("smpte2084", "arib-std-b67"):
        raise WorkflowError("HDR source needs an explicit SDR conversion; no implicit color conversion")
    if any(abs(float(x.get("rotation", 0))) > 0.01 for x in info["video"].get("side_data_list", [])):
        raise WorkflowError("Normalize source rotation before using ROI coordinates")
    o = pref["output"]
    if o["fps"] not in (30, 60) or o["width"] != 1080 or o["height"] != 1920:
        raise WorkflowError("v0.1 supports 1080x1920 with integer 30/60 fps")
    if not plan.get("segments"):
        raise WorkflowError("An explicit edit plan is required; silence is never used to remove scenes")
    for i, s in enumerate(plan["segments"]):
        if s.get("kind", "play") not in ("play", "freeze"):
            raise WorkflowError("kind must be play or freeze; replay uses a repeated play segment")
        num(s["in"], f"segment {i} in", 0, info["duration"] - 0.001)
        if s.get("kind", "play") == "freeze":
            num(s["duration"], "freeze duration", 1/o["fps"], 10)
        else:
            num(s["out"], "out", s["in"] + 1/o["fps"], info["duration"] + .01)
            num(s.get("speed", 1), "speed", .5, 2)
        if not s.get("reason"):
            raise WorkflowError("Every cut/freeze/focus needs a visible reason")
        if s.get("focus"):
            roi = s["focus"]
            if set(roi) != {"x", "y", "w", "h"}:
                raise WorkflowError("focus needs x,y,w,h in normalized SOURCE coordinates")
            for k in roi:
                num(roi[k], f"focus {k}", 0 if k in ("x", "y") else .02, 1)
            if roi["x"] + roi["w"] > 1.00001 or roi["y"] + roi["h"] > 1.00001:
                raise WorkflowError("focus lies outside source")
    seq, duration = timeline(plan["segments"], o["fps"])
    if duration > min(180, o.get("max_duration", 180)):
        raise WorkflowError("Output exceeds configured length / Shorts 180 second ceiling")
    originals = {c["id"]:c for c in p["comments"]}
    if len(originals) != len(p["comments"]) or len(set(c["id"] for c in plan.get("comments", []))) != len(plan.get("comments", [])):
        raise WorkflowError("Comment IDs must be unique")
    captions = []
    for c in plan.get("comments", []):
        if c["id"] not in originals:
            raise WorkflowError("Additional jokes belong in proposed_comments, not original comments")
        original = originals[c["id"]]
        text = c.get("display_text", original["text"])
        if text != original["text"] and not (c.get("change_reason") and c.get("change_accepted") is True):
            raise WorkflowError("Changed comment needs change_reason and change_accepted; original is preserved")
        if not isinstance(text, str) or not text.strip() or len(text) > 300:
            raise WorkflowError("Comment must be a nonempty text up to 300 characters")
        start = frame_time(num(c["start"], "comment start", 0, duration), o["fps"])
        end = frame_time(num(c["end"], "comment end", start+1/o["fps"], duration+.01), o["fps"])
        mode = original.get("mode", "subtitle")
        if mode not in ("subtitle", "voice_subtitle"):
            raise WorkflowError("mode: subtitle or voice_subtitle")
        spoken = original.get("pronunciation_text", text)
        if spoken != text and not original.get("pronunciation_reason"):
            raise WorkflowError("Pronunciation-only change requires pronunciation_reason")
        for k in ("x", "y"):
            num(c.get(k, pref["caption"][k]), f"caption {k}", 0, 1)
        if original.get("requested_start") is not None and abs(start-original["requested_start"]) > .5/o["fps"]:
            raise WorkflowError("Explicit requested_start is in OUTPUT seconds and must be honored")
        if original.get("requested_end") is not None and abs(end-original["requested_end"]) > .5/o["fps"]:
            raise WorkflowError("Explicit requested_end must be honored")
        for k in ("x", "y"):
            if original.get("requested_"+k) is not None and c.get(k, pref["caption"][k]) != original["requested_"+k]:
                raise WorkflowError("Explicit requested caption position must be honored")
        voice = None
        if mode == "voice_subtitle":
            if original.get("voice_file"):
                if original.get("voice_transcript") != text:
                    raise WorkflowError("Supplied voice needs voice_transcript exactly matching display text; listen to verify")
                voice = media_path(path.parent, original["voice_file"])
            else:
                indexpath = path.parent / "generated/voices/index.json"
                index = read_json(indexpath) if indexpath.exists() else {}
                entry = index.get(c["id"])
                if not entry or entry.get("signature") != voice_signature(p, original, text, pref, entry.get("engine_version")):
                    raise WorkflowError(f"Missing/stale VOICEVOX audio for {c['id']}; run tts after plan changes")
                voice = media_path(path.parent, entry["file"])
                if sha(voice) != entry["sha256"]:
                    raise WorkflowError("Voice file changed; regenerate")
            vd = probe(voice)
            if not vd["audio"] or vd["duration"] <= 0:
                raise WorkflowError("Voice file needs audio")
            if vd["duration"] > end-start + .02:
                raise WorkflowError(f"Voice for {c['id']} takes {vd['duration']:.2f}s but subtitle lasts {end-start:.2f}s; extend it or regenerate speed")
        caption = {**c, "start":start,"end":end,"text":text,"spoken":spoken,"mode":mode,"voice":str(voice) if voice else None}
        from .remotion import validate_caption
        validate_caption(caption, path.parent, o["fps"])
        captions.append(caption)
    if set(originals) != {c["id"] for c in captions}:
        raise WorkflowError("Every original comment must be placed; empty project comments are allowed")
    for s in plan.get("sfx", []):
        f = media_path(path.parent, s["file"])
        if not s.get("reason"):
            raise WorkflowError("SFX needs a reason")
        num(s["start"], "sfx start", 0, duration)
        if s["start"] + probe(f)["duration"] > duration + .02:
            raise WorkflowError("SFX overflows video; trim the supplied file explicitly")
    warnings = []
    budget = max(1, math.ceil(duration/30))
    if sum(bool(s.get("focus")) for s in seq) > pref["editorial"]["max_focus_events_per_30s"]*budget:
        warnings.append("Focus events exceed saved preference; review pacing")
    if len(plan.get("sfx", [])) > pref["editorial"]["max_sfx_per_30s"]*budget:
        warnings.append("SFX events exceed saved preference")
    return {"project_path":path,"project":p,"prefs":pref,"plan":plan,"source":source,"info":info,
            "segments":seq,"duration":duration,"comments":captions,"warnings":warnings}


def http_json(url, data=None, query=None):
    if query:
        url += "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(),
                                     headers={"Content-Type":"application/json"})
    if query and data is None:
        request.method = "POST"
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError) as e:
        raise WorkflowError("VOICEVOX unavailable; launch its engine on 127.0.0.1:50021") from e


def voice_base(pref):
    url = pref["voicevox_url"].rstrip("/")
    u = urllib.parse.urlsplit(url)
    if u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost"):
        raise WorkflowError("VOICEVOX URL must use local loopback")
    return url


def voice_signature(p, comment, text, pref, version):
    settings = {**p.get("voicevox", {}), **comment.get("voice_settings", {})}
    payload = {"text":comment.get("pronunciation_text", text),"settings":settings,
               "version":version,"engine":pref["voicevox_url"]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def synthesize(project, plan=None):
    path, p, pref = load(project)
    base = voice_base(pref)
    speakers = json.loads(http_json(base+"/speakers"))
    version = json.loads(http_json(base+"/version"))
    styles = {style["id"]:(speaker, style) for speaker in speakers for style in speaker["styles"]}
    overrides = {x["id"]:x for x in read_json(plan).get("comments", [])} if plan else {}
    dest = path.parent / "generated/voices"
    dest.mkdir(parents=True, exist_ok=True)
    index = {}
    for c in p["comments"]:
        if c.get("mode", "subtitle") != "voice_subtitle" or c.get("voice_file"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]+", c["id"]):
            raise WorkflowError("VOICEVOX comment IDs must be alphanumeric/-/_")
        text = overrides.get(c["id"], {}).get("display_text", c["text"])
        spoken = c.get("pronunciation_text", text)
        if spoken != text and not c.get("pronunciation_reason"):
            raise WorkflowError("Add pronunciation_reason for phonetic spelling")
        settings = {**p.get("voicevox", {}), **c.get("voice_settings", {})}
        sid = settings.get("speaker_id")
        if sid not in styles:
            raise WorkflowError("Select an installed speaker_id with owshort speakers; no implicit speaker")
        speed = num(settings.get("speed", 1), "voice speed", .5, 2)
        query = json.loads(http_json(base+"/audio_query", query={"text":spoken,"speaker":sid}))
        query.update(speedScale=speed, prePhonemeLength=num(settings.get("pre_pause", .05), "pre pause", 0, 2),
                     postPhonemeLength=num(settings.get("post_pause", .1), "post pause", 0, 2), outputSamplingRate=48000,
                     outputStereo=True)
        if "pause_scale" in settings:
            if "pauseLengthScale" not in query:
                raise WorkflowError("Installed VOICEVOX does not support pauseLengthScale")
            query["pauseLengthScale"] = num(settings["pause_scale"], "pause scale", 0, 2)
        signature = voice_signature(p, c, text, pref, version)
        name = c["id"] + "-" + signature[:12]
        target = dest / (name + ".wav")
        if not target.exists():
            wav = http_json(base+f"/synthesis?speaker={sid}", query)
            if wav[:4] != b"RIFF":
                raise WorkflowError("VOICEVOX did not return WAV")
            target.write_bytes(wav)
        speaker, style = styles[sid]
        license_data = json.loads(http_json(base+f"/speaker_info?speaker_uuid={speaker['speaker_uuid']}"))
        (dest / (name+"-license.txt")).write_text(license_data.get("policy", "Policy not returned; consult speaker terms"), encoding="utf-8")
        write_json(dest / (name+"-query.json"), query)
        index[c["id"]] = {"file":str(target.relative_to(path.parent)),"signature":signature,"sha256":sha(target),
                          "engine_version":version,"display_text":text,"pronunciation_text":spoken,
                          "credit":f"VOICEVOX:{speaker['name']}","style":style["name"],"duration":probe(target)["duration"]}
    write_json(dest / "index.json", index)
    return index


def font_for(pref, size, text):
    from PIL import ImageFont
    fpath = Path(pref["font_path"])
    if not fpath.is_absolute():
        fpath = ROOT / fpath
    if not fpath.exists():
        raise WorkflowError(f"Font missing: {fpath}; specify a Japanese font in preferences.json")
    font = ImageFont.truetype(str(fpath), size)
    # Reject tofu-only fonts for Japanese; don't silently ship unreadable subtitles.
    chars = list(dict.fromkeys(c for c in text if '\u3040' <= c <= '\u9fff'))[:8]
    missing = bytes(font.getmask('\uffff'))
    if any(bytes(font.getmask(c)) == missing for c in chars):
        raise WorkflowError("Selected font lacks a required Japanese glyph")
    return font


def caption_image(text, target, pref, scale=1):
    from PIL import Image, ImageDraw
    cap = pref["caption"]
    size = round(cap["size"]*scale)
    num(cap["size"], "caption size", 24, 150)
    font = font_for(pref, size, text)
    width = int(pref["output"]["width"] * cap["max_width"] * scale)
    stroke = max(1, round(cap["stroke"]*scale))
    image = Image.new("RGBA", (width, round(size*1.45)*cap["max_lines"]+stroke*4))
    draw = ImageDraw.Draw(image)
    lines, line = [], ""
    for char in text:
        if char == "\n":
            lines.append(line); line = ""; continue
        if draw.textlength(line+char, font=font) > width-stroke*4:
            lines.append(line); line = char
        else:
            line += char
    lines.append(line)
    # Prefer the setup/punchline boundary over leaving a tiny final line.
    if len(lines) > 1 and "……" in text and "\n" not in text:
        first,second = text.split("……",1)
        candidate = [first+"……",second]
        if second and all(draw.textlength(x,font=font) <= width-stroke*4 for x in candidate):
            lines = candidate
    if len(lines) > cap["max_lines"]:
        raise WorkflowError("Caption exceeds max_lines; split comments or change size/width; no text is dropped")
    draw.multiline_text((width//2,stroke*2), "\n".join(lines), font=font, fill=cap["color"],
                        anchor="ma", align="center", stroke_width=stroke, stroke_fill="#151725", spacing=round(size*.3))
    bbox = image.getbbox()
    if not bbox:
        raise WorkflowError("Empty caption image")
    image.crop((0, max(0,bbox[1]-stroke), width, min(image.height,bbox[3]+stroke))).save(target)


def srt_time(t):
    ms = round(t*1000)
    return f"{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}"


def write_srt(comments, target):
    Path(target).write_text("\n\n".join(f"{i}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{c['text']}" for i,c in enumerate(comments, 1))+"\n", encoding="utf-8-sig")


def rect(pref, label, w, h):
    l = pref["layout"]
    return [round(l[label+"_"+key]*dimension/2)*2 for key,dimension in (("x",w),("y",h),("width",w),("height",h))]


def video_filter(pref, segment, w, h, fps, srcinfo):
    x,y,mw,mh = rect(pref,"main",w,h)
    fx,fy,fw,fh = rect(pref,"focus",w,h)
    parts = [f"[0:v]setpts=(PTS-STARTPTS)/{segment.get('speed',1)},fps={fps},setsar=1,split={3 if segment.get('focus') else 2}[bg][main]" + ("[crop]" if segment.get("focus") else ""),
             f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=12:2,eq=brightness=-0.28[back]",
             f"[main]scale={mw}:{mh}:force_original_aspect_ratio=decrease,pad={mw}:{mh}:(ow-iw)/2:(oh-ih)/2:color=0x121724[screen]",
             f"[back][screen]overlay={x}:{y}:shortest=1[base]"]
    if segment.get("focus"):
        r = segment["focus"]
        sw,sh = srcinfo["width"],srcinfo["height"]
        cw,ch = max(2,int(r["w"]*sw)//2*2),max(2,int(r["h"]*sh)//2*2)
        cx,cy = min(int(r["x"]*sw)//2*2,sw-cw),min(int(r["y"]*sh)//2*2,sh-ch)
        parts += [f"[crop]crop={cw}:{ch}:{cx}:{cy},scale={fw}:{fh}:force_original_aspect_ratio=increase,crop={fw}:{fh}[detail]",
                  f"[base][detail]overlay={fx}:{fy}:shortest=1[v]"]
    else:
        parts += ["[base]null[v]"]
    return ";".join(parts)


def mix_stem(events, target, duration, gain_db):
    args = ["-f","lavfi","-i",f"anullsrc=r=48000:cl=stereo:d={duration}"]
    parts, labels = [], ["[0:a]"]
    for i, e in enumerate(events, 1):
        args += ["-i", e["file"]]
        delay = round(e["start"]*1000)
        gain = num(e.get("gain_db",gain_db), "gain_db", -60, 20)
        parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS,volume={gain}dB,adelay={delay}|{delay}[e{i}]")
        labels.append(f"[e{i}]")
    parts += ["".join(labels)+f"amix=inputs={len(labels)}:normalize=0:duration=first[a]"]
    ff([*args,"-filter_complex_threads","1","-filter_complex",";".join(parts),"-map","[a]","-t",str(duration),"-c:a","pcm_f32le",target])


def render(project, plan, stage="preview"):
    ctx = validate(project, plan)
    path,p,pref = ctx["project_path"],ctx["project"],ctx["prefs"]
    scale = pref["output"].get("preview_scale",.5) if stage == "preview" else 1
    num(scale,"preview_scale",.25,1)
    w,h,fps = round(1080*scale/2)*2,round(1920*scale/2)*2,pref["output"]["fps"]
    dest = path.parent / "build" / (datetime.now().strftime("%Y%m%d-%H%M%S-%f")+"-"+stage)
    dest.mkdir(parents=True)
    write_json(dest / "plan.snapshot.json",ctx["plan"])
    write_json(dest / "preferences.snapshot.json",pref)
    write_json(dest / "project.snapshot.json",p)
    source = ctx["source"]
    manifest = {"schema_version":1,"stage":stage,"created_at":now(),"duration":ctx["duration"],"source_sha256":sha(source),
                "warnings":ctx["warnings"],"segments":ctx["segments"],"premiere_import_status":"UNVERIFIED",
                "tool_versions":{"python":platform.python_version(),"ffmpeg":run(["ffmpeg","-version"]).splitlines()[0]},
                "voice_listening_status":"NOT_VERIFIED","status":"RENDERING"}
    write_json(dest / "manifest.json",manifest)
    parts = dest / "segments"
    parts.mkdir()
    videos, games = [], []
    try:
        for i,s in enumerate(ctx["segments"]):
            vpath,apath = parts/f"{i:03}.mp4", parts/f"{i:03}.wav"
            d = s["frames"]/fps
            if s.get("kind", "play") == "freeze":
                still = parts/f"{i:03}.png"
                ff(["-ss",str(s["in"]),"-i",source,"-frames:v","1",still])
                inputs = ["-loop","1","-framerate",str(fps),"-i",still]
                ff(["-f","lavfi","-i",f"anullsrc=r=48000:cl=stereo:d={d}","-c:a","pcm_f32le",apath])
            else:
                inputs = ["-ss",str(s["in"]),"-t",str(s["out"]-s["in"]),"-i",source]
                if ctx["info"]["audio"]:
                    audio = f"asetpts=PTS-STARTPTS,atempo={s.get('speed',1)},aresample=48000,aformat=channel_layouts=stereo,volume={pref['audio']['game_gain_db']}dB,apad,atrim=duration={d}"
                    ff([*inputs,"-vn","-af",audio,"-t",str(d),"-c:a","pcm_f32le",apath])
                else:
                    ff(["-f","lavfi","-i",f"anullsrc=r=48000:cl=stereo:d={d}","-c:a","pcm_f32le",apath])
            graph = video_filter(pref,s,w,h,fps,ctx["info"]["video"])
            ff([*inputs,"-filter_complex_threads","1","-filter_complex",graph,"-map","[v]","-an","-frames:v",str(s["frames"]),
                "-c:v","libx264","-preset","veryfast","-crf","18","-pix_fmt","yuv420p",vpath])
            videos.append(vpath); games.append(apath)
        # Fixed relative filenames avoid concat escaping problems for Japanese/space/quote paths.
        (parts/"video.concat").write_text("\n".join(f"file '{v.name}'" for v in videos),encoding="utf-8")
        (parts/"audio.concat").write_text("\n".join(f"file '{v.name}'" for v in games),encoding="utf-8")
        ff(["-f","concat","-safe","1","-i","video.concat","-c","copy","../picture.mp4"],cwd=parts)
        ff(["-f","concat","-safe","1","-i","audio.concat","-c:a","pcm_f32le","../game.wav"],cwd=parts)
        mix_stem([{"file":c["voice"],"start":c["start"]} for c in ctx["comments"] if c["voice"]],dest/"voice.wav",ctx["duration"],pref["audio"]["voice_gain_db"])
        mix_stem([{**s,"file":media_path(path.parent,s["file"])} for s in ctx["plan"].get("sfx",[])],dest/"sfx.wav",ctx["duration"],pref["audio"]["sfx_gain_db"])
        graph = "[1:a]asplit=2[trigger][voice];[0:a][trigger]sidechaincompress=threshold=0.035:ratio=5:attack=12:release=200[game];[game][voice][2:a]amix=inputs=3:normalize=0:duration=longest[mix]" if pref["audio"].get("duck",True) else "[0:a][1:a][2:a]amix=inputs=3:normalize=0:duration=longest[mix]"
        graph += f";[mix]loudnorm=I={pref['audio']['target_lufs']}:TP={pref['audio']['true_peak_db']}:LRA=9:print_format=json,aresample=48000[a]"
        ff(["-loglevel","info","-i",dest/"game.wav","-i",dest/"voice.wav","-i",dest/"sfx.wav","-filter_complex_threads","1","-filter_complex",graph,"-map","[a]","-t",str(ctx["duration"]),"-c:a","pcm_s24le",dest/"mix.wav"],log=dest/"mix.log")
        captions = dest / "captions"
        captions.mkdir()
        args = ["-i",dest/"picture.mp4","-i",dest/"mix.wav"]
        graph, last = [], "0:v"
        remotion_assets = []
        for i,c in enumerate(ctx["comments"]):
            target = captions / f"{i:03}.png"
            caption_image(c["text"],target,pref,scale)
            x,y = c.get("x",pref["caption"]["x"]),c.get("y",pref["caption"]["y"])
            from PIL import Image
            im = Image.open(target)
            px,py = round(x*w-im.width/2),round(y*h-im.height/2)
            if px < 0 or py < 0 or px+im.width > w or py+im.height > h:
                raise WorkflowError("Caption lies outside canvas; choose a visible position")
            canvas = Image.new("RGBA",(w,h))
            canvas.paste(im,(px,py))
            canvas.save(captions/f"{i:03}-canvas.png")
            if c.get("renderer") == "remotion":
                from .remotion import render_caption
                movie, record = render_caption(ctx, c, dest, i, w, h)
                remotion_assets.append(record)
                args += ["-i",movie]
                graph.append(f"[{i+2}:v]setpts=PTS-STARTPTS+{c['start']}/TB[rm{i}]")
                graph.append(f"[{last}][rm{i}]overlay=x=0:y=0:enable='gte(t,{c['start']})*lt(t,{c['end']})':eof_action=pass:repeatlast=0[v{i}]")
            else:
                args += ["-loop","1","-framerate",str(fps),"-i",target]
                graph.append(f"[{last}][{i+2}:v]overlay=x={x}*W-w/2:y={y}*H-h/2:enable='gte(t,{c['start']})*lt(t,{c['end']})':eof_action=repeat[v{i}]")
            last = f"v{i}"
        if graph:
            args += ["-filter_complex_threads","1","-filter_complex",";".join(graph),"-map",f"[{last}]"]
        else:
            args += ["-map","0:v"]
        filename = "preview.mp4" if stage == "preview" else "master.mp4"
        ff([*args,"-map","1:a","-t",str(ctx["duration"]),"-c:v","libx264","-preset","veryfast","-crf","18","-pix_fmt","yuv420p","-r",str(fps),
            "-c:a","aac","-b:a","192k","-ar","48000","-movflags","+faststart",dest/filename])
        write_srt(ctx["comments"],dest/"captions.srt")
        export_handoff(ctx,dest,w,h)
        if remotion_assets:
            manifest["remotion_captions"] = remotion_assets
            with (dest/"edit-notes.md").open("a", encoding="utf-8") as notes:
                notes.write("\n指定字幕のみRemotionの透明MOVで合成。Premiere XMLの字幕は静止PNGの代替。動きはMP4とremotion/*.movに保存。\n")
        from .premiere import export_xml
        export_xml(ctx,dest,w,h)
        out = probe(dest/filename)
        if (out["video"]["width"],out["video"]["height"]) != (w,h) or abs(out["duration"]-ctx["duration"]) > .1:
            raise WorkflowError("Output dimensions/duration differ from plan")
        ff(["-i",dest/filename,"-f","null","-"])
        manifest.update(status="RENDERED",completed_at=now(),video=filename,video_sha256=sha(dest/filename),output_probe=out,
                        assets={f.name:sha(f) for f in (dest/"picture.mp4",dest/"game.wav",dest/"voice.wav",dest/"sfx.wav",dest/"mix.wav")})
        write_json(dest/"manifest.json",manifest)
        write_json(path.parent/f"latest-{stage}.json", {"build":str(dest),"video":str(dest/filename)})
        return dest
    except Exception as e:
        manifest.update(status="FAILED",error=str(e))
        write_json(dest/"manifest.json",manifest)
        raise


def export_handoff(ctx,dest,w,h):
    p = ctx["project"]
    metadata = copy.deepcopy(p.get("metadata",{}))
    metadata.setdefault("title", "")
    metadata.setdefault("description", "")
    metadata.setdefault("hashtags", [])
    generated = ctx["project_path"].parent/"generated/voices/index.json"
    index = read_json(generated) if generated.exists() else {}
    originals = {c["id"]:c for c in p["comments"]}
    credits = sorted(set(index[c["id"]]["credit"] for c in ctx["comments"]
                         if c["voice"] and not originals[c["id"]].get("voice_file") and c["id"] in index))
    credits += p.get("audio_credits", [])
    credits = sorted(set(credits))
    metadata["credits"] = credits
    metadata["description_with_credits"] = metadata["description"] + ("\n\n"+"\n".join(credits) if credits else "")
    metadata["tiktok_caption"] = metadata["title"]+"\n"+metadata["description_with_credits"]+"\n"+" ".join(metadata["hashtags"])
    write_json(dest/"metadata.json",metadata)
    write_json(dest/"posting.request.json",{"schema_version":1,"youtube":{"channel_id":None,"privacy":"private","made_for_kids":None,"publish_at":None},
              "tiktok":{"username":None,"method":"browser","result_type":None,"privacy":None,"scheduled_at":None},"status":"NOT_UPLOADED"})
    (dest/"upload-text.txt").write_text(metadata["tiktok_caption"],encoding="utf-8")
    notes = ["# 編集内容",f"長さ: {ctx['duration']:.3f}秒 / {w}×{h}","時刻は完成動画基準。原文は project.snapshot.json に保存。",""]
    for s in ctx["segments"]:
        notes.append(f"- {s['start']:.3f}–{s['end']:.3f}: 元動画 {s['in']:.3f}秒 / {s.get('kind','play')} / {s['reason']}")
    for c in ctx["comments"]:
        notes.append(f"- {c['start']:.3f}–{c['end']:.3f}: {c['text']} ({c['mode']}) / 発音: {c['spoken']}")
    notes += ["", "## 提案のみ（映像には追加していない）",json.dumps(ctx["plan"].get("proposed_comments",[]),ensure_ascii=False),
              "", "Premiere XML は生成した候補。Premiere本体での読み込み未検証。", "画像の部分拡大と縦配置は picture.mp4 に焼き込み。字幕はPNG素材とSRTに分離。"]
    (dest/"edit-notes.md").write_text("\n".join(notes),encoding="utf-8")


def analyze(project, interval=1):
    from PIL import Image, ImageDraw, ImageFont
    path,p,pref = load(project)
    num(interval,"analysis interval",.2,10)
    dest = path.parent/"analysis"
    dest.mkdir(exist_ok=True)
    items = [{"file":p["source"],"role":"source"}]+p.get("references",[])
    report = {"created_at":now(),"media":[],"limitations":["Technical measurements and frame samples only; not semantic gameplay analysis.","Listen to audio proxies; no speech recognition is performed."]}
    for i,entry in enumerate(items):
        if entry.get("url"):
            report["media"].append({**entry,"inspection":"NOT_INSPECTED_URL","action":"Provide the reference video file or describe timestamps/pacing/caption design."})
            continue
        source = media_path(path.parent,entry["file"])
        info = probe(source)
        folder = dest/f"{i:02}-{entry.get('role','reference')}"
        folder.mkdir(exist_ok=True)
        for old in folder.glob("frame-*.jpg"):
            old.unlink()
        ff(["-i",source,"-vf",f"fps=1/{interval}:start_time=0,scale=480:-2","-q:v","3",folder/"frame-%05d.jpg"])
        frames = sorted(folder.glob("frame-*.jpg"))
        for offset in range(0,len(frames),24):
            subset = frames[offset:offset+24]
            sheet = Image.new("RGB",(4*480,6*300),"#151b28")
            draw = ImageDraw.Draw(sheet)
            for j,frame in enumerate(subset):
                im = Image.open(frame); im.thumbnail((480,270))
                xx,yy = (j%4)*480,(j//4)*300
                sheet.paste(im,(xx,yy+25))
                draw.text((xx+8,yy+4),f"sample {(offset+j)*interval:.2f}s (approx)",font=ImageFont.load_default(),fill="white")
            sheet.save(folder/f"contact-{offset//24:03}.jpg")
        if info["audio"]:
            ff(["-i",source,"-vn","-ac","1","-ar","24000","-c:a","pcm_s16le",folder/"listen.wav"])
        ff(["-i",source,"-vf","scale=640:-2","-c:v","libx264","-preset","veryfast","-crf","26","-c:a","aac",folder/"proxy.mp4"])
        report["media"].append({**entry,"inspection":"TECHNICAL_SAMPLES_READY","sha256":sha(source),"probe":info,"samples":str(folder),"semantic_review":"PENDING"})
    write_json(dest/"report.json",report)
    return dest


def doctor():
    report = {"created_at":now(),"platform":platform.platform(),"python":platform.python_version(),"tools":{},"voicevox":"NOT_CHECKED","premiere":"NOT_VERIFIED"}
    for tool in ("ffmpeg","ffprobe","codex","node","npm","winget"):
        executable = shutil.which(tool)
        report["tools"][tool] = {"found":bool(executable)}
        if executable:
            # Don't dump paths/account data. Avoid Windows .cmd shell quoting.
            if Path(executable).suffix.lower() not in (".cmd", ".bat"):
                try:
                    report["tools"][tool]["version"] = run([executable,"-version" if tool.startswith("ff") else "--version"]).splitlines()[0]
                except Exception:
                    report["tools"][tool]["version"] = "CHECK_FAILED"
    try:
        report["voicevox"] = json.loads(http_json("http://127.0.0.1:50021/version"))
    except WorkflowError:
        report["voicevox"] = "NOT_RUNNING"
    if os.name == "nt":
        try:
            raw = run(["powershell.exe","-NoProfile","-Command", "Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber | ConvertTo-Json -Compress"])
            report["windows"] = json.loads(raw)
            report["hardware"] = json.loads(run(["powershell.exe","-NoProfile","-Command", "@{CPU=(Get-CimInstance Win32_Processor | Select-Object -ExpandProperty Name); RAM_GB=[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB); GPU=(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion)} | ConvertTo-Json -Depth 4 -Compress"]))
        except Exception:
            report["windows"] = "CHECK_FAILED"
    return report


def feedback(prefpath,key,value,note):
    prefpath = Path(prefpath)
    p = read_json(prefpath)
    allowed = {"caption.size", "audio.sfx_gain_db", "editorial.max_focus_events_per_30s",
               "editorial.max_sfx_per_30s", "editorial.punchline_pause_seconds", "editorial.prefer_reactions_over_explanation"}
    if key not in allowed:
        raise WorkflowError("Unsupported preference key")
    if key == "editorial.prefer_reactions_over_explanation":
        if not isinstance(value,bool):
            raise WorkflowError("Boolean value required")
    else:
        num(value,key, -60 if key == "audio.sfx_gain_db" else 0, 150)
    section,k = key.split(".")
    before = p[section][k]
    backup = prefpath.with_name(prefpath.stem+"-"+datetime.now().strftime("%Y%m%d-%H%M%S-%f")+".json")
    shutil.copy2(prefpath,backup)
    p[section][k] = value
    p["feedback_history"].append({"at":now(),"key":key,"before":before,"after":value,"note":note})
    write_json(prefpath,p)
    return p
