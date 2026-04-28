import React from 'react';
import { useCurrentFrame, useVideoConfig, spring, interpolate, AbsoluteFill } from 'remotion';
import type { ScenePlanItem } from '../../types';

interface KineticInsightProps {
  scene: ScenePlanItem;
  accentColor: string;
}

export const KineticInsight: React.FC<KineticInsightProps> = ({ scene, accentColor }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  const title = scene.title || "БЕЗ ЗАГОЛОВКА";
  const subtitle = scene.subtitle || "";
  const facts = scene.facts || [];
  const insight = scene.insight || "";
  const words = title.split(' ');

  // 1. Анимация появления подзаголовка (сразу)
  const subtitleEntry = spring({ fps, frame, config: { damping: 12 } });

  // 2. Медленный зум всего слайда для динамики
  const globalScale = interpolate(frame, [0, durationInFrames], [1, 1.05]);

  return (
    <AbsoluteFill style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '0 80px',
      transform: `scale(${globalScale})`,
    }}>
      
      {/* 1. ПОДЗАГОЛОВОК (Верхний контекст) */}
      {subtitle && (
        <div style={{
          position: 'absolute',
          top: '12%',
          fontFamily: '"Inter", sans-serif',
          fontSize: 34,
          fontWeight: 600,
          color: accentColor,
          letterSpacing: '0.25em',
          textTransform: 'uppercase',
          opacity: subtitleEntry,
          transform: `translateY(${interpolate(subtitleEntry, [0, 1], [-20, 0])}px)`,
        }}>
          {subtitle}
        </div>
      )}

      {/* 2. ГЛАВНЫЙ ЗАГОЛОВОК (Огромный, смещен чуть вверх) */}
      <div style={{
        display: 'flex',
        flexWrap: 'wrap',
        justifyContent: 'center',
        gap: '15px 30px',
        maxWidth: '1600px',
        marginBottom: '40px',
        transform: `translateY(${facts.length > 0 ? '-60px' : '0'})`,
      }}>
        {words.map((word, i) => {
          const wordDelay = 5 + (i * 3);
          const spr = spring({ fps, frame: frame - wordDelay, config: { damping: 14, stiffness: 140 } });
          const isAccent = word.length > 5 || word.match(/[0-9]/) || word === word.toUpperCase();

          return (
            <span key={i} style={{
              fontFamily: '"Inter", sans-serif',
              fontSize: 140, // Еще больше!
              fontWeight: 950,
              color: isAccent ? accentColor : 'white',
              opacity: interpolate(spr, [0, 1], [0, 1]),
              transform: `scale(${interpolate(spr, [0, 1], [0.85, 1])})`,
              display: 'inline-block',
              lineHeight: 0.85,
              letterSpacing: '-0.06em',
              textShadow: isAccent ? `0 0 60px ${accentColor}44` : '0 10px 30px rgba(0,0,0,0.5)',
            }}>
              {word}
            </span>
          );
        })}
      </div>

      {/* 3. ФАКТЫ / БУЛЛИТЫ (Появляются после заголовка) */}
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '25px',
        marginTop: '20px',
        maxWidth: '1200px',
      }}>
        {facts.map((fact, i) => {
          const factDelay = 30 + (i * 15); // Начинают вылетать через 1 сек
          const spr = spring({ fps, frame: frame - factDelay, config: { damping: 15 } });
          
          return (
            <div key={i} style={{
              display: 'flex',
              alignItems: 'center',
              gap: '25px',
              opacity: interpolate(spr, [0, 1], [0, 1]),
              transform: `translateX(${interpolate(spr, [0, 1], [-40, 0])}px)`,
            }}>
              <div style={{ width: 12, height: 12, borderRadius: '50%', background: accentColor }} />
              <div style={{
                fontFamily: '"Inter", sans-serif',
                fontSize: 42,
                fontWeight: 500,
                color: 'white',
                lineHeight: 1.2,
                opacity: 0.9,
              }}>
                {fact}
              </div>
            </div>
          );
        })}
      </div>

      {/* 4. ФИНАЛЬНЫЙ ВЫВОД (Снизу) */}
      {insight && (
        <div style={{
          position: 'absolute',
          bottom: '15%',
          backgroundColor: `${accentColor}11`,
          padding: '20px 40px',
          borderRadius: '20px',
          border: `1px solid ${accentColor}33`,
          backdropFilter: 'blur(10px)',
          fontFamily: '"Inter", sans-serif',
          fontSize: 34,
          fontWeight: 600,
          color: 'white',
          opacity: spring({ fps, frame: frame - 80, config: { damping: 12 } }),
          transform: `translateY(${interpolate(spring({ fps, frame: frame - 80 }), [0, 1], [20, 0])}px)`,
        }}>
          💡 {insight}
        </div>
      )}

      {/* 5. ИНДИКАТОР ВРЕМЕНИ (Прогресс-бар снизу) */}
      <div style={{
        position: 'absolute',
        bottom: 0,
        left: 0,
        height: 8,
        background: `linear-gradient(90, transparent, ${accentColor})`,
        width: `${(frame / durationInFrames) * 100}%`,
        opacity: 0.6,
      }} />

    </AbsoluteFill>
  );
};
