import copy
import io
import json
import os
import shutil
import tempfile
import threading
import unittest
import wave
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from owshort import core
from owshort.youtube import classify,final_build


def test_font():
    candidates = [os.environ.get("OWSHORT_TEST_FONT", ""),"C:/Windows/Fonts/meiryob.ttc","/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    return next(Path(x) for x in candidates if x and Path(x).is_file())


class ContractTests(unittest.TestCase):
    def test_timeline_frame_accumulation(self):
        seq,d = core.timeline([{"in":0,"out":1.01},{"in":1.01,"out":2.01,"speed":2},{"kind":"freeze","in":2,"duration":.41}],30)
        self.assertEqual([x["frames"] for x in seq],[30,15,12])
        self.assertEqual(d,57/30)
        self.assertEqual(seq[2]["start"],1.5)

    def test_private_processing_is_not_complete(self):
        item = {"snippet":{"channelId":"target"},"status":{"privacyStatus":"private","uploadStatus":"uploaded"},"processingDetails":{"processingStatus":"processing"}}
        self.assertEqual(classify(item,"target"),"UPLOADED_PROCESSING")
        item["processingDetails"]["processingStatus"] = "succeeded"
        self.assertEqual(classify(item,"target"),"COMPLETE_PRIVATE")
        item["status"]["privacyStatus"] = "public"
        self.assertEqual(classify(item,"target"),"PRIVACY_MISMATCH")
        self.assertEqual(classify(item,"other"),"ACCOUNT_MISMATCH")
        item["status"]["uploadStatus"] = "rejected"
        self.assertEqual(classify(item,"target"),"FAILED")

    def test_invalid_time_is_rejected(self):
        for value in (float("nan"),float("inf"),True,-1):
            with self.assertRaises(core.WorkflowError):
                core.num(value,"time",0)

    def test_feedback_history_and_backup(self):
        with tempfile.TemporaryDirectory() as t:
            f = Path(t)/"preferences.json"
            shutil.copy2(core.ROOT/"config/preferences.json",f)
            core.feedback(f,"caption.size",84,"字幕を大きく")
            p = core.read_json(f)
            self.assertEqual(p["caption"]["size"],84)
            self.assertEqual(p["feedback_history"][0]["before"],72)
            self.assertEqual(len(list(Path(t).glob("preferences-*.json"))),1)


class MediaIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="owshort-media-")
        cls.base = Path(cls.tmp.name)
        font = test_font()
        cls.japanese = bool(os.environ.get("OWSHORT_TEST_FONT")) or os.name == "nt"
        pref = core.read_json(core.ROOT/"config/preferences.json")
        pref["font_path"] = str(font)
        core.write_json(cls.base/"preferences.json",pref)
        source = cls.base/"素材 test's video.mp4"
        core.ff(["-f","lavfi","-i","testsrc2=size=960x540:rate=24:duration=3","-f","lavfi","-i","sine=frequency=240:sample_rate=48000:duration=3",
                 "-c:v","libx264","-preset","ultrafast","-threads","2","-pix_fmt","yuv420p","-c:a","aac",source])
        core.ff(["-f","lavfi","-i","sine=frequency=660:sample_rate=48000:duration=0.5","-c:a","pcm_s16le",cls.base/"provided.wav"])
        core.ff(["-f","lavfi","-i","sine=frequency=1000:sample_rate=48000:duration=0.1","-c:a","pcm_s16le",cls.base/"sfx.wav"])
        with io.BytesIO() as memory:
            with wave.open(memory,"wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000); w.writeframes(b"\x00\x00"*24000)
            cls.mock_wav = memory.getvalue()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass
            def do_GET(self):
                if self.path == "/version": value = "MOCK-TEST-ONLY"
                elif self.path == "/speakers": value = [{"name":"テスト音声（実話者ではない）","speaker_uuid":"mock","styles":[{"id":123,"name":"テスト"}]}]
                elif self.path.startswith("/speaker_info"): value = {"policy":"Synthetic mock service. No real speech generated."}
                else:
                    self.send_error(404); return
                self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(value).encode())
            def do_POST(self):
                if self.path.startswith("/audio_query"):
                    data = json.dumps({"accent_phrases":[],"speedScale":1,"prePhonemeLength":0.1,"postPhonemeLength":0.1,"pauseLengthScale":1}).encode()
                elif self.path.startswith("/synthesis"):
                    self.rfile.read(int(self.headers.get("Content-Length",0)))
                    data = cls.mock_wav
                else:
                    self.send_error(404); return
                self.send_response(200); self.end_headers(); self.wfile.write(data)
        cls.server = ThreadingHTTPServer(("127.0.0.1",0),Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True); cls.thread.start()
        pref["voicevox_url"] = f"http://127.0.0.1:{cls.server.server_port}"
        core.write_json(cls.base/"preferences.json",pref)
        texts = ["ヒール来ると思ったのに","そっち行くんかい！","耐えられる？……無理でした"] if cls.japanese else ["Expected a heal", "Wrong direction!", "Could survive? Nope."]
        cls.project = {"schema_version":1,"synthetic_test":True,"source":source.name,"preferences":"preferences.json", "voicevox":{"speaker_id":123,"speed":1.1,"pause_scale":.8},
            "comments":[{"id":"c1","text":texts[0],"mode":"voice_subtitle"},{"id":"c2","text":texts[1],"mode":"subtitle"},
                        {"id":"c3","text":texts[2],"mode":"voice_subtitle","voice_file":"provided.wav","voice_transcript":texts[2]}],
            "references":[{"url":"https://example.com/reference","role":"reference"}],
            "audio_credits":["TEST ONLY: mock silence and test tones, not VOICEVOX speech"],
            "metadata":{"title":"合成テスト映像（Overwatch素材ではありません）","description":"レンダー検証用。音声はテスト信号。","hashtags":["#test"]}}
        core.write_json(cls.base/"project.json",cls.project)
        cls.plan = {"schema_version":1,"segments":[
            {"in":0,"out":.8,"reason":"test setup"},{"in":.8,"out":1.6,"focus":{"x":.35,"y":.3,"w":.3,"h":.3},"reason":"test focus while full frame stays visible"},
            {"kind":"freeze","in":1.6,"duration":.3,"reason":"test pause"},{"in":1.6,"out":2.4,"reason":"test result"},{"in":1.6,"out":2,"reason":"test replay"}],
            "comments":[{"id":"c1","start":0,"end":1.2},{"id":"c2","start":1.2,"end":2.1},{"id":"c3","start":2.1,"end":3.1}],
            "sfx":[{"file":"sfx.wav","start":2.2,"reason":"test landing"}],"proposed_comments":[]}
        core.write_json(cls.base/"plan.json",cls.plan)
        core.synthesize(cls.base/"project.json",cls.base/"plan.json")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.tmp.cleanup()

    def test_mock_voicevox_contract_and_cache_staleness(self):
        index = core.read_json(self.base/"generated/voices/index.json")
        self.assertEqual(index["c1"]["display_text"],self.project["comments"][0]["text"])
        self.assertEqual(index["c1"]["engine_version"],"MOCK-TEST-ONLY")
        changed = copy.deepcopy(self.project); changed["voicevox"]["speed"] = 1.4
        core.write_json(self.base/"changed.json",changed)
        with self.assertRaisesRegex(core.WorkflowError,"stale"):
            core.validate(self.base/"changed.json",self.plan)

    def test_voice_overflow_and_original_preservation(self):
        plan = copy.deepcopy(self.plan); plan["comments"][0]["end"] = .2
        with self.assertRaisesRegex(core.WorkflowError,"takes"):
            core.validate(self.base/"project.json",plan)
        plan = copy.deepcopy(self.plan); plan["comments"][0]["display_text"] = "changed joke"
        with self.assertRaisesRegex(core.WorkflowError,"Changed comment"):
            core.validate(self.base/"project.json",plan)

    def test_source_bounds_and_explicit_timing(self):
        plan = copy.deepcopy(self.plan); plan["segments"][1]["focus"]["x"] = .9
        with self.assertRaisesRegex(core.WorkflowError,"outside source"):
            core.validate(self.base/"project.json",plan)
        plan = copy.deepcopy(self.plan); plan["segments"][0]["out"] = 9
        with self.assertRaises(core.WorkflowError):
            core.validate(self.base/"project.json",plan)
        p = copy.deepcopy(self.project); p["comments"][0]["requested_start"] = .1
        core.write_json(self.base/"requested.json",p)
        with self.assertRaisesRegex(core.WorkflowError,"requested_start"):
            core.validate(self.base/"requested.json",self.plan)

    def test_reference_url_remains_uninspected(self):
        dest = core.analyze(self.base/"project.json",1)
        report = core.read_json(dest/"report.json")
        self.assertEqual(report["media"][1]["inspection"],"NOT_INSPECTED_URL")
        self.assertEqual(report["media"][0]["semantic_review"],"PENDING")

    def test_render_preview_final_and_xml_assets(self):
        import xml.etree.ElementTree as ET
        from urllib.parse import unquote,urlsplit
        preview = core.render(self.base/"project.json",self.plan,"preview")
        final = core.render(self.base/"project.json",self.plan,"final")
        manifest = core.read_json(final/"manifest.json")
        self.assertEqual(manifest["status"],"RENDERED")
        self.assertEqual(manifest["premiere_import_status"],"UNVERIFIED")
        self.assertEqual(manifest["output_probe"]["video"]["width"],1080)
        self.assertEqual(manifest["output_probe"]["video"]["height"],1920)
        self.assertAlmostEqual(manifest["duration"],3.1)
        for xml in ("review-timeline.xml","editable-timeline.xml"):
            doc = ET.parse(final/xml)
            for el in doc.findall(".//pathurl"):
                uri = urlsplit(el.text)
                decoded = unquote(uri.path)
                if os.name == "nt" and decoded.startswith("/"): decoded = decoded[1:]
                self.assertTrue(Path(decoded).exists())
        self.assertEqual(len(ET.parse(final/"editable-timeline.xml").findall(".//sequence/media/audio/track")),3)
        with self.assertRaisesRegex(core.WorkflowError,"Synthetic"):
            final_build(final)
        if os.environ.get("OWSHORT_SAMPLE_DEST"):
            dest = Path(os.environ["OWSHORT_SAMPLE_DEST"]); dest.mkdir(parents=True,exist_ok=True)
            shutil.copy2(preview/"preview.mp4",dest/"synthetic-preview.mp4")
            shutil.copy2(final/"master.mp4",dest/"synthetic-master.mp4")
            shutil.copy2(final/"mix.log",dest/"synthetic-mix.log")
            core.write_json(dest/"synthetic-summary.json",{"duration":manifest["duration"],"size":[1080,1920],"status":"RENDERED",
                "premiere":"UNVERIFIED","voicevox":"MOCK_CONTRACT_ONLY","upload":"NOT_ATTEMPTED","japanese_font_test":self.japanese})

    def test_silent_source_speed_and_no_captions(self):
        source = self.base/"silent.mp4"
        core.ff(["-i",self.base/self.project["source"],"-an","-c:v","copy",source])
        project = copy.deepcopy(self.project)
        project.update(source=source.name,comments=[])
        core.write_json(self.base/"silent-project.json",project)
        plan = {"schema_version":1,"segments":[{"in":0,"out":2,"speed":2,"reason":"explicit speed test, not silence removal"}],"comments":[],"sfx":[]}
        build = core.render(self.base/"silent-project.json",plan,"preview")
        info = core.probe(build/"preview.mp4")
        self.assertAlmostEqual(info["duration"],1.0,places=1)
        self.assertIsNotNone(info["audio"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
