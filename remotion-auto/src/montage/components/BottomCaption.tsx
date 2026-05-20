import React from 'react';
import {AbsoluteFill, useVideoConfig} from 'remotion';

interface BottomCaptionProps {
  text: string;
}

const clamp = (value: number, min: number, max: number): number => Math.max(min, Math.min(max, value));

export const BottomCaption: React.FC<BottomCaptionProps> = ({text}) => {
  const {width} = useVideoConfig();
  const safeText = String(text || '').trim();
  if (!safeText) return null;

  const len = safeText.length;
  const baseSize = width >= 1400 ? 58 : width >= 1000 ? 50 : 42;
  const adaptive = baseSize - Math.max(0, (len - 28) * 0.4);
  const fontSize = clamp(adaptive, 30, baseSize);
  const lineHeight = 1.08;

  return (
    <AbsoluteFill style={{justifyContent: 'flex-end', pointerEvents: 'none'}}>
      <div
        style={{
          width: '100%',
          padding: '0 4.5% 7.6%',
          boxSizing: 'border-box',
          display: 'flex',
          justifyContent: 'center',
        }}
      >
        <div
          style={{
            maxWidth: '86%',
            minHeight: 82,
            padding: '16px 34px 18px',
            borderRadius: 14,
            background: 'rgba(0,0,0,0.88)',
            boxShadow: '0 10px 28px rgba(0,0,0,0.45)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#FFFFFF',
            fontFamily: 'Montserrat, Arial, sans-serif',
            fontWeight: 900,
            fontSize,
            lineHeight,
            textAlign: 'center',
            textTransform: 'uppercase',
            letterSpacing: '-0.01em',
            WebkitTextStroke: '0.75px rgba(0,0,0,0.85)',
            paintOrder: 'stroke fill',
            textShadow: '0 2px 10px rgba(0,0,0,0.65)',
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
