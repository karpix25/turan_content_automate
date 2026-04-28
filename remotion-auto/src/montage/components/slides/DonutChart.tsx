import React from 'react';
import { useCurrentFrame, useVideoConfig, interpolate } from 'remotion';
import type { ScenePlanItem } from '../../types';

interface DonutChartProps {
  scene: ScenePlanItem;
  accentColor: string;
}

const COLORS = [
  '#7BD2FF', // cyan
  '#00ff88', // green
  '#ffaa00', // amber
  '#ff4d6d', // rose
];

interface DonutRingProps {
  value: number; // 0-1
  label: string;
  color: string;
  frame: number;
  index: number;
  radius?: number;
}

const DonutRing: React.FC<DonutRingProps> = ({ value, label, color, frame, index, radius = 85 }) => {
  const circumference = 2 * Math.PI * radius;

  const progress = interpolate(
    frame - index * 8,
    [0, 35],
    [0, value],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );

  const offset = circumference - progress * circumference;
  const displayPct = Math.round(
    interpolate(frame - index * 8, [0, 35], [0, value * 100], {
      extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    })
  );

  const size = (radius + 20) * 2;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 20 }}>
      <div style={{ position: 'relative', width: size, height: size }}>
        {/* Background ring */}
        <svg width={size} height={size} style={{ position: 'absolute', inset: 0, transform: 'rotate(-90deg)' }}>
          <circle
            cx={size / 2} cy={size / 2} r={radius}
            fill="none"
            stroke="rgba(255,255,255,0.06)"
            strokeWidth={10}
          />
          <circle
            cx={size / 2} cy={size / 2} r={radius}
            fill="none"
            stroke={color}
            strokeWidth={10}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            style={{ filter: `drop-shadow(0 0 8px ${color}66)` }}
          />
        </svg>

        {/* Center value */}
        <div style={{
          position: 'absolute', inset: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexDirection: 'column',
        }}>
          <span style={{
            fontFamily: '"Inter", "Montserrat", sans-serif',
            fontSize: radius > 70 ? 48 : 36,
            fontWeight: 800,
            color: 'white',
            lineHeight: 1,
            letterSpacing: '-0.04em',
          }}>
            {displayPct}
          </span>
          <span style={{
            fontFamily: '"Inter", "Montserrat", sans-serif',
            fontSize: 22,
            fontWeight: 600,
            color,
          }}>%</span>
        </div>
      </div>

      {/* Label */}
      <div style={{
        fontFamily: '"Inter", "Montserrat", sans-serif',
        fontSize: 17,
        fontWeight: 500,
        color: 'rgba(255,255,255,0.55)',
        textAlign: 'center',
        maxWidth: size,
        lineHeight: 1.35,
      }}>
        {label}
      </div>
    </div>
  );
};

export const DonutChart: React.FC<DonutChartProps> = ({ scene, accentColor }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const bars = (scene.bars || []).slice(0, 3);
  const colors = [accentColor, ...COLORS.filter(c => c !== accentColor)];

  const displayTitle = scene.title || scene.keyword || '';

  const fadeIn = interpolate(frame, [0, 15], [0, 1], { extrapolateRight: 'clamp' });

  return (
    <div style={{
      width: '100%', height: '100%',
      display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      padding: '60px 80px',
      opacity: fadeIn,
    }}>
      {/* Title */}
      {displayTitle && (
        <div style={{
          fontFamily: '"Inter", "Montserrat", sans-serif',
          fontSize: 28,
          fontWeight: 600,
          color: 'rgba(255,255,255,0.7)',
          textTransform: 'uppercase',
          letterSpacing: 3,
          marginBottom: 60,
        }}>
          {displayTitle}
        </div>
      )}

      {/* Rings */}
      <div style={{
        display: 'flex',
        gap: bars.length === 1 ? 0 : 80,
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        {bars.map((bar, i) => (
          <DonutRing
            key={i}
            value={bar.value}
            label={bar.label}
            color={colors[i % colors.length]}
            frame={frame}
            index={i}
            radius={bars.length === 1 ? 120 : 85}
          />
        ))}
      </div>
    </div>
  );
};
