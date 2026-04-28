import React from 'react';
import { useCurrentFrame, interpolate } from 'remotion';
import type { ScenePlanItem } from '../../types';

interface BarChartProps {
  scene: ScenePlanItem;
  accentColor: string;
}

export const BarChart: React.FC<BarChartProps> = ({ scene, accentColor }) => {
  const frame = useCurrentFrame();

  const bars = (scene.bars || []).slice(0, 5);
  const displayTitle = scene.title || scene.keyword || '';
  const displaySubtitle = scene.subtitle || '';

  const fadeIn = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: 'clamp' });

  return (
    <div style={{
      width: '100%', height: '100%',
      display: 'flex', flexDirection: 'column',
      justifyContent: 'center',
      padding: '80px 120px',
      opacity: fadeIn,
    }}>
      {/* Header */}
      <div style={{ marginBottom: 56 }}>
        {displaySubtitle && (
          <div style={{
            fontFamily: '"Inter", "Montserrat", sans-serif',
            fontSize: 18,
            fontWeight: 500,
            color: accentColor,
            textTransform: 'uppercase',
            letterSpacing: 3,
            marginBottom: 12,
          }}>
            {displaySubtitle}
          </div>
        )}
        {displayTitle && (
          <div style={{
            fontFamily: '"Inter", "Montserrat", sans-serif',
            fontSize: 40,
            fontWeight: 700,
            color: 'white',
            letterSpacing: '-0.03em',
            lineHeight: 1.1,
          }}>
            {displayTitle}
          </div>
        )}
      </div>

      {/* Bars */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
        {bars.map((bar, i) => {
          const width = interpolate(
            frame - 8 - i * 6,
            [0, 25],
            [0, bar.value * 100],
            { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
          );

          const itemOpacity = interpolate(
            frame - i * 5,
            [0, 10],
            [0, 1],
            { extrapolateRight: 'clamp' }
          );

          const pct = Math.round(
            interpolate(frame - 8 - i * 6, [0, 25], [0, bar.value * 100], {
              extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
            })
          );

          return (
            <div key={i} style={{ opacity: itemOpacity }}>
              {/* Label + value */}
              <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'baseline',
                marginBottom: 10,
              }}>
                <span style={{
                  fontFamily: '"Inter", "Montserrat", sans-serif',
                  fontSize: 20,
                  fontWeight: 500,
                  color: 'rgba(255,255,255,0.75)',
                }}>
                  {bar.label}
                </span>
                <span style={{
                  fontFamily: '"Inter", "Montserrat", sans-serif',
                  fontSize: 22,
                  fontWeight: 700,
                  color: accentColor,
                  letterSpacing: '-0.02em',
                }}>
                  {pct}%
                </span>
              </div>

              {/* Bar track */}
              <div style={{
                height: 6,
                background: 'rgba(255,255,255,0.06)',
                borderRadius: 3,
                overflow: 'hidden',
              }}>
                <div style={{
                  height: '100%',
                  width: `${width}%`,
                  background: `linear-gradient(90deg, ${accentColor} 0%, ${accentColor}bb 100%)`,
                  borderRadius: 3,
                  boxShadow: `0 0 12px ${accentColor}44`,
                }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
