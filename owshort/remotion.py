"""Opt-in Remotion caption generation; FFmpeg remains the main video renderer."""
import os
import shutil
from pathlib import Path
from . import core

APP = core.ROOT / 'remotion'


def validate_caption(comment, base, fps):
    renderer = comment.get('renderer', 'default')
    if renderer not in ('default', 'remotion'):
        raise core.WorkflowError('caption renderer must be default or remotion')
    if renderer != 'remotion':
        if 'remotion' in comment:
            raise core.WorkflowError('remotion options require renderer: remotion')
        return
    options = comment.get('remotion')
    if not isinstance(options, dict) or not isinstance(options.get('request'), str) or not options['request'].strip():
        raise core.WorkflowError('Remotion caption needs remotion.request with the user instruction')
    if options.get('effect', 'bounce') not in ('bounce', 'word-highlight', 'bounce-highlight'):
        raise core.WorkflowError('Unknown Remotion caption effect; use a custom entry_point for custom effects')
    if 'entry_point' in options:
        core.media_path(base, options['entry_point'])
    if 'props' in options and not isinstance(options['props'], dict):
        raise core.WorkflowError('remotion.props must be an object')
    core.num(options.get('bounce_height', 45), 'bounce_height', 0, 300)
    if 'tokens' in options:
        tokens = options['tokens']
        if not isinstance(tokens, list) or not tokens or any(not isinstance(t, dict) or not isinstance(t.get('text'), str) for t in tokens):
            raise core.WorkflowError('remotion.tokens must contain text/start/end objects')
        if ''.join(t['text'] for t in tokens) != comment['text']:
            raise core.WorkflowError('Remotion tokens must preserve the complete caption text, including spaces')
        previous = 0
        duration = comment['end'] - comment['start']
        for token in tokens:
            start = core.num(token.get('start'), 'token start', previous, duration)
            end = core.num(token.get('end'), 'token end', start + 1/fps, duration + .00001)
            previous = end


def browser_path():
    explicit = os.environ.get('OWSHORT_REMOTION_BROWSER')
    if explicit:
        return str(core.media_path(Path.cwd(), explicit))
    candidates = [
        Path(os.environ.get('PROGRAMFILES', 'C:/Program Files')) / 'Google/Chrome/Application/chrome.exe',
        Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe',
    ]
    return next((str(p) for p in candidates if p.is_file()), None)


def render_caption(ctx, comment, dest, index, width, height):
    node = shutil.which('node')
    if not node or not (APP / 'node_modules/@remotion/renderer/package.json').is_file():
        raise core.WorkflowError('Remotion is not installed. Run npm.cmd ci in remotion/; no automatic fallback was used.')
    options = comment['remotion']
    folder = dest / 'remotion'
    folder.mkdir(exist_ok=True)
    entry = core.media_path(ctx['project_path'].parent, options['entry_point']) if options.get('entry_point') else APP/'src/index.tsx'
    pref = ctx['prefs']
    fps = pref['output']['fps']
    scale = width / 1080
    props = {**{k: v for k, v in options.get('props', {}).items() if k != 'tokens'},
             'text': comment['text'], 'width': width, 'height': height, 'fps': fps,
             'durationInFrames': round((comment['end']-comment['start'])*fps),
             'x': comment.get('x', pref['caption']['x']), 'y': comment.get('y', pref['caption']['y']),
             'fontSize': pref['caption']['size']*scale, 'stroke': pref['caption']['stroke']*scale,
             'color': pref['caption']['color'], 'maxWidth': pref['caption']['max_width'],
             'effect': options.get('effect', 'bounce'), 'bounceHeight': options.get('bounce_height', 45)}
    if 'tokens' in options:
        props['tokens'] = options['tokens']
    movie = folder / f'{index:03}.mov'
    request = {'entryPoint': str(entry.resolve()), 'compositionId': options.get('composition_id', 'Caption'),
               'output': str(movie.resolve()), 'bundleDir': str((folder/f'bundle-{index:03}').resolve()),
               'browserExecutable': browser_path(), 'inputProps': props}
    request_path = folder / f'{index:03}.request.json'
    core.write_json(request_path, request)
    core.run([node, APP/'render.mjs', request_path.resolve()], cwd=APP, log=folder/f'{index:03}.log')
    info = core.probe(movie)
    video = info['video'] or {}
    if (video.get('width'), video.get('height')) != (width, height) or abs(info['duration'] - props['durationInFrames']/fps) > .02:
        raise core.WorkflowError('Remotion output size/duration does not match the caption')
    if not video.get('pix_fmt', '').startswith(('yuva', 'rgba', 'argb', 'bgra', 'gbrap')):
        raise core.WorkflowError('Remotion output has no alpha channel')
    record = {'comment_id': comment['id'], 'renderer': 'remotion', 'file': str(movie.relative_to(dest)),
              'start': comment['start'], 'end': comment['end'], 'sha256': core.sha(movie),
              'entry_sha256': core.sha(entry), 'request': options['request'], 'alpha': True,
              'input_props': props}
    core.write_json(folder/f'{index:03}.json', record)
    return movie, record
