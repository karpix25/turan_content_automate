import React from 'react';
import { AbsoluteFill, useCurrentFrame, interpolate, spring, useVideoConfig } from 'remotion';
import { KineticInsight } from './slides/KineticInsight';
import type { ScenePlanItem } from '../types';

interface FullSlideProps {
  scene: ScenePlanItem;
}

export const FullSlide: React.FC<FullSlideProps> = ({ scene }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Общая анимация появления всего слайда
  const intro = spring({
    fps,
    frame,
    config: { damping: 15 },
  });

  const opacity = interpolate(intro, [0, 1], [0, 1]);

  // Выбираем акцентный цвет (можем добавить логику смены цветов)
  const accentColor = "#FFD700"; // Золотой/Желтый - хорошо читается и выглядит премиально

  return (
    <AbsoluteFill>
      {/* Затемнение фона без backdrop blur: CSS blur слишком дорогой для длинного Remotion-рендера. */}
      <AbsoluteFill style={{
        backgroundColor: 'rgba(0,0,0,0.4)',
        opacity,
      }} />

      {/* Огромные буквы смысла */}
      <KineticInsight 
        scene={scene} 
        accentColor={accentColor} 
      />

      {/* Легкий градиент по краям для фокуса в центр */}
      <AbsoluteFill style={{
        background: 'radial-gradient(circle, transparent 30%, rgba(0,0,0,0.5) 100%)',
        pointerEvents: 'none',
      }} />
    </AbsoluteFill>
  );
};
