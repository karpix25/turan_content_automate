import React from 'react';
import { useCurrentFrame, interpolate, spring, useVideoConfig } from 'remotion';
import type { ScenePlanItem } from '../../types';

interface ComparisonCardProps {
  scene: ScenePlanItem;
  accentColor: string;
}

export const ComparisonCard: React.FC<ComparisonCardProps> = ({ scene, accentColor }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enterA = spring({ fps, frame, config: { damping: 20, stiffness: 130, mass: 0.9 } });
  const enterB = spring({ fps, frame: frame - 8, config: { damping: 20, stiffness: 130, mass: 0.9 } });

  const bars = (scene.bars || []).slice(0, 2);
  const displayTitle = scene.title || scene.keyword || '';

  // Derive before/after from bars or explicit fields
  const before = bars[0] || { label: 'Раньше', value: 0.2 };
  const after = bars[1] || { label: 'Сейчас', value: 0.8 };

  const translateLeft = interpolate(enterA, [0, 1], [-60, 0]);
  const translateRight = interpolate(enterB, [0, 1], [60, 0]);
  const opacityA = interpolate(enterA, [0, 1], [0, 1]);
  const opacityB = interpolate(enterB, [0, 1], [0, 1]);

  return (
    <div style={{
      width: '100%', height: '100%',
      display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      padding: '80px 100px',
    }}>
      {/* Title */}
      {displayTitle && (
        <div style={{
          fontFamily: '"Inter", "Montserrat", sans-serif',
          fontSize: 28,
          fontWeight: 600,
          color: 'rgba(255,255,255,0.5)',
          textTransform: 'uppercase',
          letterSpacing: 3,
          marginBottom: 56,
          opacity: interpolate(frame, [0, 12], [0, 1], { extrapolateRight: 'clamp' }),
        }}>
          {displayTitle}
        </div>
      )}

      {/* Two cards side by side */}
      <div style={{ display: 'flex', gap: 24, width: '100%', alignItems: 'stretch' }}>
        {/* BEFORE */}
        <div style={{
          flex: 1,
          background: 'rgba(255,255,255,0.03)',
          border: '1px solid rgba(255,255,255,0.08)',
          borderRadius: 24,
          padding: '48px 40px',
          display: 'flex', flexDirection: 'column',
          justifyContent: 'space-between',
          transform: `translateX(${translateLeft}px)`,
          opacity: opacityA,
        }}>
          <div style={{
            fontFamily: '"Inter", "Montserrat", sans-serif',
            fontSize: 14,
            fontWeight: 600,
            color: 'rgba(255,255,255,0.3)',
            textTransform: 'uppercase',
            letterSpacing: 3,
          }}>
            БЫЛО
          </div>
          <div>
            <div style={{
              fontFamily: '"Inter", "Montserrat", sans-serif',
              fontSize: 72,
              fontWeight: 800,
              color: 'rgba(255,255,255,0.6)',
              letterSpacing: '-0.05em',
              lineHeight: 1,
              marginBottom: 12,
            }}>
              {Math.round(before.value * 100)}%
            </div>
            <div style={{
              fontFamily: '"Inter", "Montserrat", sans-serif',
              fontSize: 20,
              color: 'rgba(255,255,255,0.4)',
              lineHeight: 1.4,
            }}>
              {before.label}
            </div>
          </div>
        </div>

        {/* Arrow divider */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 32, color: accentColor,
          opacity: interpolate(frame, [10, 20], [0, 1], { extrapolateRight: 'clamp' }),
          flexShrink: 0,
        }}>
          →
        </div>

        {/* AFTER */}
        <div style={{
          flex: 1,
          background: `${accentColor}10`,
          border: `1px solid ${accentColor}30`,
          borderRadius: 24,
          padding: '48px 40px',
          display: 'flex', flexDirection: 'column',
          justifyContent: 'space-between',
          transform: `translateX(${translateRight}px)`,
          opacity: opacityB,
        }}>
          <div style={{
            fontFamily: '"Inter", "Montserrat", sans-serif',
            fontSize: 14,
            fontWeight: 600,
            color: accentColor,
            textTransform: 'uppercase',
            letterSpacing: 3,
            opacity: 0.8,
          }}>
            СТАЛО
          </div>
          <div>
            <div style={{
              fontFamily: '"Inter", "Montserrat", sans-serif',
              fontSize: 72,
              fontWeight: 800,
              color: accentColor,
              letterSpacing: '-0.05em',
              lineHeight: 1,
              marginBottom: 12,
              textShadow: `0 0 40px ${accentColor}44`,
            }}>
              {Math.round(after.value * 100)}%
            </div>
            <div style={{
              fontFamily: '"Inter", "Montserrat", sans-serif',
              fontSize: 20,
              color: 'rgba(255,255,255,0.6)',
              lineHeight: 1.4,
            }}>
              {after.label}
            </div>
          </div>
        </div>
      </div>

      {/* Insight below */}
      {(scene.facts?.[0] || scene.insight) && (
        <div style={{
          marginTop: 40,
          fontFamily: '"Inter", "Montserrat", sans-serif',
          fontSize: 18,
          color: 'rgba(255,255,255,0.35)',
          textAlign: 'center',
          opacity: interpolate(frame, [20, 35], [0, 1], { extrapolateRight: 'clamp' }),
        }}>
          {scene.facts?.[0] || scene.insight}
        </div>
      )}
    </div>
  );
};
