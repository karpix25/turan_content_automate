import React from 'react';
import { useCurrentFrame, useVideoConfig, interpolate, spring } from 'remotion';
import type { ScenePlanItem } from '../types';

interface MiniAccentProps {
  scene: ScenePlanItem;
  accentColor: string;
}

// Picks the best content for a mini accent
const getMiniContent = (scene: ScenePlanItem): { value: string; label: string } => {
  // Prefer structured fields
  if (scene.value !== undefined && scene.title) {
    return {
      value: `${scene.value}${scene.unit || '%'}`,
      label: scene.title,
    };
  }

  // Extract number from bars
  const firstBar = scene.bars?.[0];
  if (firstBar) {
    return {
      value: `${Math.round(firstBar.value * 100)}%`,
      label: firstBar.label,
    };
  }

  // Fallback: use keyword + first fact
  const fact = scene.facts?.[0] || scene.steps?.[0] || scene.insight || '';
  return {
    value: scene.keyword || '→',
    label: fact.slice(0, 60),
  };
};

export const MiniAccent: React.FC<MiniAccentProps> = ({ scene, accentColor }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const sceneDuration = (scene.end - scene.start) * fps;

  // Slide in
  const slideIn = spring({
    fps,
    frame,
    config: { damping: 20, stiffness: 160, mass: 0.7 },
  });

  // Fade out in last 20 frames
  const fadeOut = interpolate(
    frame,
    [sceneDuration - 20, sceneDuration - 5],
    [1, 0],
    { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' }
  );

  const translateX = interpolate(slideIn, [0, 1], [-340, 0]);
  const opacity = Math.min(slideIn, fadeOut);

  const { value, label } = getMiniContent(scene);

  return (
    <div
      style={{
        position: 'absolute',
        bottom: 80,
        left: 60,
        display: 'flex',
        alignItems: 'center',
        gap: 20,
        transform: `translateX(${translateX}px)`,
        opacity,
        zIndex: 20,
      }}
    >
      {/* Accent line */}
      <div style={{
        width: 4,
        height: 70,
        background: accentColor,
        borderRadius: 2,
        boxShadow: `0 0 16px ${accentColor}88`,
      }} />

      {/* Content */}
      <div style={{
        background: 'rgba(6, 6, 10, 0.88)',
        backdropFilter: 'blur(20px)',
        borderRadius: 16,
        padding: '18px 28px',
        border: `1px solid rgba(255,255,255,0.08)`,
        maxWidth: 400,
      }}>
        {/* Primary value */}
        <div style={{
          fontFamily: '"Inter", "Montserrat", sans-serif',
          fontSize: 40,
          fontWeight: 800,
          color: accentColor,
          lineHeight: 1,
          letterSpacing: '-0.03em',
        }}>
          {value}
        </div>

        {/* Label */}
        {label && (
          <div style={{
            fontFamily: '"Inter", "Montserrat", sans-serif',
            fontSize: 16,
            fontWeight: 500,
            color: 'rgba(255,255,255,0.65)',
            marginTop: 6,
            lineHeight: 1.3,
          }}>
            {label}
          </div>
        )}
      </div>
    </div>
  );
};
