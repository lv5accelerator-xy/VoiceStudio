import React from 'react';
import { AbsoluteFill, Composition, registerRoot, useCurrentFrame, useVideoConfig } from 'remotion';

function Scene({ bpm }) {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const pulse = 1 - ((frame * bpm / (fps * 60)) % 1);
  const fade = Math.max(0, Math.min(1, frame / 8, (durationInFrames - frame) / 8));
  return (
    <AbsoluteFill style={{ background: '#131a2b' }}>
      <AbsoluteFill style={{
        background: 'radial-gradient(ellipse at 50% 44%, #34598a 0%, #182239 45%, #111827 75%)',
        opacity: fade * (0.45 + 0.3 * pulse),
        transform: `scale(${1 + pulse * 0.03})`,
      }} />
    </AbsoluteFill>
  );
}

registerRoot(() => <Composition id="MusicBackdrop" component={Scene} fps={30} width={1080} height={1920}
  durationInFrames={30} defaultProps={{ bpm: 96, duration: 1, width: 1080, height: 1920 }}
  calculateMetadata={({ props }) => ({
    width: props.width, height: props.height, durationInFrames: Math.max(1, Math.ceil(props.duration * 30)),
  })} />);
