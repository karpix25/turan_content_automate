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
  const baseSize = width >= 1400 ? 72 : width >= 1000 ? 62 : 52;
  const adaptive = baseSize - Math.max(0, (len - 34) * 0.45);
  const fontSize = clamp(adaptive, 32, baseSize);
  const lineHeight = 1.04;

  return (
    <AbsoluteFill style={{justifyContent: 'flex-end', pointerEvents: 'none'}}>
      <div
        style={{
          width: '100%',
          padding: '0 4.5% 5.2%',
          boxSizing: 'border-box',
          display: 'flex',
          justifyContent: 'center',
        }}
      >
        <div
          style={{
            maxWidth: '92%',
            color: '#FFFFFF',
            fontFamily: 'Montserrat, Arial, sans-serif',
            fontWeight: 900,
            fontSize,
            lineHeight,
            textAlign: 'center',
            textTransform: 'uppercase',
            letterSpacing: '-0.01em',
            WebkitTextStroke: '10px rgba(0,0,0,0.98)',
            paintOrder: 'stroke fill',
            textShadow: '0 4px 14px rgba(0,0,0,0.5)',
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
