"""Generate conservative FCP7 xmeml candidates. Premiere round-trip is a separate real-PC check."""
import xml.etree.ElementTree as ET
from .core import write_json


def node(parent,name,text=None,**attrs):
    el = ET.SubElement(parent,name,attrs)
    if text is not None:
        el.text = str(text)
    return el


def rate(parent,fps):
    r = node(parent,"rate")
    node(r,"timebase",fps)
    node(r,"ntsc","FALSE")


def file_node(parent,filename,identifier,duration,fps,w,h,kind="video",still=False):
    f = node(parent,"file",id=identifier)
    node(f,"name",filename.name)
    node(f,"pathurl",filename.resolve().as_uri())
    rate(f,fps)
    node(f,"duration",duration)
    media = node(f,"media")
    if kind == "video":
        video = node(media,"video")
        sc = node(video,"samplecharacteristics")
        rate(sc,fps)
        node(sc,"width",w); node(sc,"height",h)
        node(sc,"pixelaspectratio","square"); node(sc,"fielddominance","none")
        if still:
            node(video,"stillframe","TRUE")
    else:
        audio = node(media,"audio")
        node(audio,"channelcount",2)
        sc = node(audio,"samplecharacteristics")
        node(sc,"depth",24); node(sc,"samplerate",48000)
    return f


def clip(track,filename,identifier,start,end,frames,fps,w,h,kind="video",still=False):
    c = node(track,"clipitem",id=identifier)
    node(c,"name",filename.name); node(c,"duration",frames)
    rate(c,fps)
    for k,v in (("start",start),("end",end),("in",0),("out",end-start)):
        node(c,k,v)
    node(c,"enabled","TRUE")
    file_node(c,filename,identifier+"-file",frames,fps,w,h,kind,still)
    st = node(c,"sourcetrack")
    node(st,"mediatype",kind); node(st,"trackindex",1)
    return c


def export_xml(ctx,dest,w,h):
    fps = ctx["prefs"]["output"]["fps"]
    duration = round(ctx["duration"]*fps)
    for editable in (False,True):
        root = ET.Element("xmeml",version="5")
        seq = node(root,"sequence",id="sequence-1")
        node(seq,"name","OW Short - "+("editable audio" if editable else "review mix"))
        node(seq,"duration",duration); rate(seq,fps)
        media = node(seq,"media")
        video = node(media,"video")
        fmt = node(video,"format"); sc = node(fmt,"samplecharacteristics")
        rate(sc,fps); node(sc,"width",w); node(sc,"height",h)
        node(sc,"pixelaspectratio","square"); node(sc,"fielddominance","none")
        track = node(video,"track")
        for i,s in enumerate(ctx["segments"]):
            clip(track,dest/"segments"/f"{i:03}.mp4",f"v-{i}",round(s["start"]*fps),round(s["end"]*fps),s["frames"],fps,w,h)
        # Separate track per caption permits overlapping captions without invalid clip overlaps.
        for i,c in enumerate(ctx["comments"]):
            track = node(video,"track")
            clip(track,dest/"captions"/f"{i:03}-canvas.png",f"caption-{i}",round(c["start"]*fps),round(c["end"]*fps),duration,fps,w,h,still=True)
        audio = node(media,"audio")
        node(audio,"numOutputChannels",2)
        for i,name in enumerate(("game.wav","voice.wav","sfx.wav") if editable else ("mix.wav",)):
            track = node(audio,"track")
            clip(track,dest/name,f"a-{i}",0,duration,duration,fps,w,h,kind="audio")
        ET.indent(root)
        filename = "editable-timeline.xml" if editable else "review-timeline.xml"
        ET.ElementTree(root).write(dest/filename,encoding="utf-8",xml_declaration=True)
    write_json(dest/"premiere-verification.json",{"status":"UNVERIFIED","application_version":None,"evidence":None,
               "checks":["XML import succeeds","all media online","1080x1920 sequence at selected fps","cut/freeze/replay timing",
                         "caption PNG position and alpha","stereo channels and sync","save/reopen .prproj","export and compare"],
               "limitations":["Layouts/ROI/speed baked into segment video; change plan and rerender to edit these.",
                              "Caption PNG appearance baked; edit text using SRT or regenerate PNG.",
                              "Editable audio XML has pre-bus stems; ducking/loudnorm must be reapplied in Premiere.",
                              "Review XML uses finished mix.wav to match FFmpeg output."]})
