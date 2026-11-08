import React, {useLayoutEffect, useRef, useState} from 'react';
import {Composition, registerRoot, useCurrentFrame, useVideoConfig,
  spring, delayRender, continueRender, cancelRender} from 'remotion';

const Caption = (p: any) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const ref = useRef<HTMLDivElement>(null);
  const [handle] = useState(() => delayRender('Check caption bounds'));
  const bounce = p.effect !== 'word-highlight';
  const highlight = p.effect !== 'bounce';
  const progress = spring({frame, fps, config: {damping: 10, stiffness: 180}});
  const offset = bounce ? (1 - progress) * (p.bounceHeight ?? 45) * width / 1080 : 0;
  const tokens = p.tokens ?? [{text: p.text, start: 0, end: p.durationInFrames / fps}];
  useLayoutEffect(() => {
    const box = ref.current!.getBoundingClientRect();
    const travel = bounce ? (p.bounceHeight ?? 45) * width / 1080 : 0;
    // Remotion may mount the composition off-screen during metadata discovery.
    // Measure text size, but compute bounds in composition coordinates.
    const left = p.x * width - box.width / 2;
    const top = p.y * height - box.height / 2;
    if (left < -1 || top - travel < -1 || left + box.width > width + 1 || top + box.height + travel > height + 1) {
      cancelRender(new Error('Remotion caption exceeds canvas; adjust size or position.'));
    } else {continueRender(handle);}
  }, [handle]);
  return <div style={{position: 'absolute', left: p.x * width, top: p.y * height,
    width: p.maxWidth * width, transform: `translate(-50%, -50%) translateY(${offset}px)`,
    textAlign: 'center'}}>
    <div ref={ref} style={{fontFamily: p.fontFamily ?? 'Meiryo, sans-serif',
      fontWeight: 800, fontSize: p.fontSize, lineHeight: 1.3, whiteSpace: 'pre-wrap',
      overflowWrap: 'anywhere', color: p.color, WebkitTextStroke: `${p.stroke}px #101820`,
      paintOrder: 'stroke fill', textShadow: '0 3px 6px #0009'}}>
      {tokens.map((token: any, i: number) => <span key={i} style={{
        color: highlight && frame / fps >= token.start && frame / fps < token.end
          ? (token.color ?? p.highlightColor ?? '#ffb52e') : p.color,
      }}>{token.text}</span>)}
    </div>
  </div>;
};

const Root = () => <Composition id="Caption" component={Caption} width={1080} height={1920}
  fps={30} durationInFrames={30} defaultProps={{text: '字幕', width: 1080, height: 1920,
    fps: 30, durationInFrames: 30, x: .5, y: .76, maxWidth: .78,
    fontSize: 72, stroke: 5, color: '#ffffff', effect: 'bounce'}}
  calculateMetadata={({props}: any) => ({width: props.width, height: props.height,
    fps: props.fps, durationInFrames: props.durationInFrames})} />;
registerRoot(Root);
