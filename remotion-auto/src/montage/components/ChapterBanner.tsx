import React from 'react';
import {interpolate, spring, useVideoConfig} from 'remotion';
import type {ScenePlanItem} from '../types';

interface ChapterBannerProps {
  scene: ScenePlanItem;
  isChapterStart: boolean;
  inSceneFrame: number;
}

const pickChapterTitle = (scene: ScenePlanItem): string => {
  const text = String(scene.chapterTitle || scene.title || scene.keyword || '').trim();
  return text || 'Новая глава';
};

const pickChapterSubtitle = (scene: ScenePlanItem): string => {
  const text = String(scene.chapterSubtitle || scene.insight || '').trim();
  return text;
};

export const ChapterBanner: React.FC<ChapterBannerProps> = ({scene, isChapterStart, inSceneFrame}) => {
  const {fps} = useVideoConfig();

  if (!isChapterStart) return null;

  const inAnim = spring({
    fps,
    frame: inSceneFrame,
    config: {damping: 18, stiffness: 130, mass: 0.8},
  });
  const holdFrames = Math.floor(2.7 * fps);
  const fadeOut = interpolate(inSceneFrame, [holdFrames - 10, holdFrames + 10], [1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const opacity = Math.min(inAnim, fadeOut);
  if (opacity <= 0.02) return null;

  const chapterNo = Number.isFinite(Number(scene.chapterIndex)) ? Number(scene.chapterIndex) : 1;
  const chapterTitle = pickChapterTitle(scene);
  const chapterSubtitle = pickChapterSubtitle(scene);

  return (
    <div
      style={{
        position: 'absolute',
        top: 52,
        left: '50%',
        transform: `translateX(-50%) translateY(${interpolate(inAnim, [0, 1], [-12, 0])}px)`,
        opacity,
        padding: '14px 22px',
        borderRadius: 14,
        border: '1px solid rgba(255,255,255,0.2)',
        background: 'rgba(7, 10, 18, 0.72)',
        backdropFilter: 'blur(8px)',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
        minWidth: 600,
        maxWidth: 1400,
        zIndex: 40,
      }}
    >
      <div
        style={{
          fontFamily: '"Inter", "Montserrat", sans-serif',
          fontSize: 20,
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: 1.4,
          color: '#ffd54f',
        }}
      >
        {`Глава ${chapterNo}`}
      </div>
      <div
        style={{
          fontFamily: '"Inter", "Montserrat", sans-serif',
          fontSize: 38,
          fontWeight: 800,
          color: '#ffffff',
          lineHeight: 1.05,
          letterSpacing: '-0.02em',
          wordBreak: 'break-word',
        }}
      >
        {chapterTitle}
      </div>
      {chapterSubtitle ? (
        <div
          style={{
            fontFamily: '"Inter", "Montserrat", sans-serif',
            fontSize: 24,
            fontWeight: 500,
            color: 'rgba(255,255,255,0.8)',
            lineHeight: 1.15,
            wordBreak: 'break-word',
          }}
        >
          {chapterSubtitle}
        </div>
      ) : null}
    </div>
  );
};
