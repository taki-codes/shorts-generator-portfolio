import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageChops, ImageStat
from owshort import core
from owshort.remotion import validate_caption


class RemotionContractTests(unittest.TestCase):
    def comment(self):
        return {'id': 'c1', 'text': '全部受け止める！', 'start': 3, 'end': 5,
                'renderer': 'remotion', 'remotion': {'request': '3秒の字幕だけRemotionで'}}

    def test_default_does_not_require_remotion(self):
        validate_caption({'text': '通常', 'start': 0, 'end': 1}, Path.cwd(), 30)

    def test_requires_explicit_renderer_and_recorded_request(self):
        c = self.comment()
        c['renderer'] = 'unknown'
        with self.assertRaises(core.WorkflowError): validate_caption(c, Path.cwd(), 30)
        c['renderer'] = 'default'
        with self.assertRaises(core.WorkflowError): validate_caption(c, Path.cwd(), 30)
        c['renderer'] = 'remotion'; c['remotion'] = {}
        with self.assertRaises(core.WorkflowError): validate_caption(c, Path.cwd(), 30)

    def test_tokens_preserve_text_and_relative_timing(self):
        c = self.comment()
        c['remotion']['tokens'] = [
            {'text': '全部', 'start': 0, 'end': .7},
            {'text': '受け止める！', 'start': .7, 'end': 2}]
        validate_caption(c, Path.cwd(), 30)
        for change in ('text', 'overflow', 'overlap'):
            altered = copy.deepcopy(c)
            token = altered['remotion']['tokens'][1]
            if change == 'text': token['text'] = '省略'
            if change == 'overflow': token['end'] = 2.2
            if change == 'overlap': token['start'] = .5
            with self.assertRaises(core.WorkflowError): validate_caption(altered, Path.cwd(), 30)


@unittest.skipUnless(os.environ.get('OWSHORT_TEST_REMOTION') == '1', 'Opt-in real local Remotion render')
class RemotionIntegrationTests(unittest.TestCase):
    def prepare_fixture(self, base):
        prefs = core.read_json(core.ROOT/'config/preferences.json')
        core.write_json(base/'preferences.json', prefs)
        core.ff(['-f', 'lavfi', '-i', 'color=c=0x204080:s=960x540:r=30:d=2',
                 '-c:v', 'libx264', '-pix_fmt', 'yuv420p', base/'source.mp4'])
        project = {'schema_version': 1, 'synthetic_test': True, 'source': 'source.mp4',
                   'preferences': 'preferences.json',
                   'comments': [{'id': 'plain', 'text': '通常字幕', 'mode': 'subtitle'},
                                {'id': 'animated', 'text': '全部受け止める！', 'mode': 'subtitle'}]}
        core.write_json(base/'project.json', project)
        plan = {'schema_version': 1, 'segments': [{'in': 0, 'out': 2, 'reason': 'synthetic test'}],
                'comments': [{'id': 'plain', 'start': 0, 'end': .3},
                             {'id': 'animated', 'start': .5, 'end': 1.3, 'renderer': 'remotion',
                              'remotion': {'request': '指定字幕だけ跳ねて色替え', 'effect': 'bounce-highlight',
                                           'tokens': [{'text': '全部', 'start': 0, 'end': .4},
                                                      {'text': '受け止める！', 'start': .4, 'end': .8}]}}]}
        return prefs, project, plan

    def test_selected_caption_alpha_timing_and_normal_caption(self):
        with tempfile.TemporaryDirectory(prefix='owshort-remotion-') as temp:
            base = Path(temp)
            prefs, project, plan = self.prepare_fixture(base)
            build = core.render(base/'project.json', plan)
            manifest = core.read_json(build/'manifest.json')
            self.assertEqual(len(manifest['remotion_captions']), 1)
            record = manifest['remotion_captions'][0]
            self.assertEqual(record['comment_id'], 'animated')
            self.assertEqual((record['start'], record['end']), (.5, 1.3))
            movie = build/record['file']
            core.ff(['-i', movie, '-frames:v', '1', base/'alpha.png'])
            alpha = Image.open(base/'alpha.png').convert('RGBA').getchannel('A')
            self.assertEqual(alpha.getextrema()[0], 0)
            self.assertGreater(alpha.getextrema()[1], 200)
            frames = {}
            for name, time in [('before', .4), ('during', .8), ('after', 1.4), ('plain', .1)]:
                target = base/f'{name}.png'
                core.ff(['-ss', str(time), '-i', build/'preview.mp4', '-frames:v', '1', target])
                frames[name] = Image.open(target).convert('RGB').crop((30, 650, 510, 840))
            def difference(a, b):
                return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean)/3
            # H.264 introduces small prediction/quantization differences between frames.
            self.assertLess(difference(frames['before'], frames['after']), .5)
            self.assertGreater(difference(frames['before'], frames['during']), 2)
            self.assertGreater(difference(frames['before'], frames['plain']), 2)
            # Without an explicit renderer, the pipeline must never call Node/Remotion.
            normal = copy.deepcopy(plan)
            del normal['comments'][1]['renderer']; del normal['comments'][1]['remotion']
            with patch('owshort.remotion.render_caption', side_effect=AssertionError('Unexpected Remotion')):
                normal_build = core.render(base/'project.json', normal)
            self.assertNotIn('remotion_captions', core.read_json(normal_build/'manifest.json'))
            if os.environ.get('OWSHORT_REMOTION_SAMPLE_DEST'):
                import shutil
                target = Path(os.environ['OWSHORT_REMOTION_SAMPLE_DEST'])
                shutil.copytree(build, target, dirs_exist_ok=False)
                for name in frames:
                    shutil.copy2(base/f'{name}.png', target/f'test-{name}.png')

    @unittest.skipUnless(
        (core.ROOT/'jobs/ow001-visor/scripts/build_preview.py').is_file(),
        'Optional private job wrapper is not included in a fresh clone')
    def test_optional_existing_job_wrapper(self):
        with tempfile.TemporaryDirectory(prefix='owshort-job-wrapper-') as temp:
            base = Path(temp)
            prefs, project, plan = self.prepare_fixture(base)
            # Exercise the existing job wrapper, custom job React code, and final scale.
            import importlib.util
            script = core.ROOT/'jobs/ow001-visor/scripts/build_preview.py'
            spec = importlib.util.spec_from_file_location('owshort_test_job_wrapper', script)
            wrapper = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(wrapper)
            Image.new('RGBA', (1080, 300), '#187f42').save(base/'header.png')
            project['header_overlay'] = {'file': 'header.png'}
            core.write_json(base/'project.json', project)
            prefs['caption']['style'] = 'fire'
            core.write_json(base/'preferences.json', prefs)
            (base/'custom.tsx').write_text('''import React from 'react';
import {Composition, registerRoot} from 'remotion';
const Custom = (p: any) => <div style={{position: 'absolute', top: p.y * p.height,
  left: p.x * p.width, transform: 'translate(-50%, -50%)', color: 'white',
  fontSize: p.fontSize, fontFamily: 'Meiryo'}}>{p.text}</div>;
registerRoot(() => <Composition id="CustomCaption" component={Custom}
  width={1080} height={1920} fps={30} durationInFrames={30} defaultProps={{}} />);
''', encoding='utf-8')
            custom = copy.deepcopy(plan)
            custom['comments'][1]['remotion'].update(entry_point='custom.tsx', composition_id='CustomCaption')
            core.write_json(base/'plan.json', custom)
            final = wrapper.render(base, 'final')
            final_manifest = core.read_json(final/'manifest.json')
            self.assertEqual(final_manifest['output_probe']['video']['width'], 1080)
            self.assertIn('header_overlay', final_manifest)
            self.assertTrue((final/'captions/000.mov').is_file())
            self.assertFalse((final/'captions/001.mov').exists(), 'Selected caption must not also generate an old fire overlay')
            self.assertEqual(final_manifest['remotion_captions'][0]['comment_id'], 'animated')


if __name__ == '__main__': unittest.main()
