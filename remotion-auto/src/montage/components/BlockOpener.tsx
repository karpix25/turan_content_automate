import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

interface BlockOpenerProps {
  text: string;
  visibleFrames: number;
  sceneFrame: number;
}

export const BlockOpener: React.FC<BlockOpenerProps> = ({text, visibleFrames, sceneFrame}) => {
  useCurrentFrame();
  const {width} = useVideoConfig();
  const safeText = String(text || '').trim();
  if (!safeText || sceneFrame >= visibleFrames) return null;

  const fadeInFrames = 10;
  const fadeOutFrames = 10;
  const opacityIn = interpolate(sceneFrame, [0, fadeInFrames], [0, 1], {extrapolateRight: 'clamp'});
  const opacityOut = interpolate(
    sceneFrame,
    [Math.max(0, visibleFrames - fadeOutFrames), visibleFrames],
    [1, 0],
    {extrapolateLeft: 'clamp'},
  );
  const opacity = Math.min(opacityIn, opacityOut);
  const translateY = interpolate(sceneFrame, [0, 12], [18, 0], {extrapolateRight: 'clamp'});

  const fontSize = width >= 1400 ? 58 : width >= 1000 ? 50 : 42;

  return (
    <AbsoluteFill style={{pointerEvents: 'none'}}>
      <div
        style={{
          position: 'absolute',
          left: '50%',
          bottom: '7.5%',
          transform: `translate(-50%, ${translateY}px)`,
          maxWidth: '86%',
          padding: '18px 28px',
          borderRadius: 20,
          background: 'rgba(0,0,0,0.56)',
          border: '1px solid rgba(255,255,255,0.16)',
          opacity,
          backdropFilter: 'blur(4px)',
        }}
      >
        <div
          style={{
            color: '#FFFFFF',
            fontFamily: 'Montserrat, Arial, sans-serif',
            fontWeight: 800,
            fontSize,
            lineHeight: 1.15,
            textAlign: 'center',
            WebkitTextStroke: '2px rgba(0,0,0,0.75)',
            paintOrder: 'stroke fill',
            textShadow: '0 2px 8px rgba(0,0,0,0.45)',
            wordBreak: 'break-word',
            overflowWrap: 'anywhere',
          }}
        >
          {safeText}
        </div>
      </div>
    </AbsoluteFill>
  );
};
