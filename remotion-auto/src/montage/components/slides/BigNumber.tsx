import React from 'react';
import { useCurrentFrame, useVideoConfig, spring, interpolate } from 'remotion';
import type { ScenePlanItem } from '../../types';

interface BigNumberProps {
  scene: ScenePlanItem;
  accentColor: string;
}

export const BigNumber: React.FC<BigNumberProps> = ({ scene, accentColor }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enter = spring({ fps, frame, config: { damping: 18, stiffness: 120, mass: 1 } });
  const opacity = interpolate(enter, [0, 1], [0, 1]);
  const scale = interpolate(enter, [0, 1], [0.85, 1]);

  // Resolve display value
  const hasNumericValue = typeof scene.value === 'number' && Number.isFinite(scene.value);
  const displayValue = hasNumericValue
    ? `${scene.value}`
    : scene.bars?.[0]
      ? `${Math.round(scene.bars[0].value * 100)}`
      : '—';

  const displayUnit = scene.unit ?? (hasNumericValue ? '' : '%');
  const displayTitle = scene.title || scene.keyword || '';
  const displayContext = scene.insight || '';
  const facts = scene.facts || scene.steps?.slice(0, 2) || [];

  return (
    <div style={{
      width: '100%',
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '80px 120px',
      opacity,
      transform: `scale(${scale})`,
    }}>
      {/* Context above */}
      {displayContext && (
        <div style={{
          fontFamily: '"Inter", "Montserrat", sans-serif',
          fontSize: 22,
          fontWeight: 500,
          color: 'rgba(255,255,255,0.45)',
          textTransform: 'uppercase',
          letterSpacing: 4,
          marginBottom: 24,
        }}>
          {displayContext}
        </div>
      )}

      {/* Big number */}
      <div style={{
        display: 'flex',
        alignItems: 'baseline',
        gap: 8,
        lineHeight: 1,
      }}>
        <span style={{
          fontFamily: '"Inter", "Montserrat", sans-serif',
          fontSize: 180,
          fontWeight: 900,
          color: 'white',
          letterSpacing: '-0.06em',
        }}>
          {displayValue}
        </span>
        <span style={{
          fontFamily: '"Inter", "Montserrat", sans-serif',
          fontSize: 80,
          fontWeight: 700,
          color: accentColor,
          letterSpacing: '-0.04em',
        }}>
          {displayUnit}
        </span>
      </div>

      {/* Title */}
      {displayTitle && (
        <div style={{
          fontFamily: '"Inter", "Montserrat", sans-serif',
          fontSize: 36,
          fontWeight: 600,
          color: 'rgba(255,255,255,0.85)',
          marginTop: 24,
          textAlign: 'center',
          letterSpacing: '-0.02em',
        }}>
          {displayTitle}
        </div>
      )}

      {/* Divider */}
      <div style={{
        width: 80,
        height: 2,
        background: accentColor,
        opacity: 0.4,
        borderRadius: 1,
        marginTop: 40,
        marginBottom: 32,
      }} />

      {/* Facts */}
      {facts.length > 0 && (
        <div style={{ display: 'flex', gap: 40 }}>
          {facts.slice(0, 2).map((fact, i) => (
            <div key={i} style={{
              fontFamily: '"Inter", "Montserrat", sans-serif',
              fontSize: 18,
              color: 'rgba(255,255,255,0.5)',
              textAlign: 'center',
              maxWidth: 280,
              lineHeight: 1.4,
              opacity: interpolate(frame - 10 - i * 5, [0, 15], [0, 1], { extrapolateRight: 'clamp' }),
            }}>
              {fact}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
