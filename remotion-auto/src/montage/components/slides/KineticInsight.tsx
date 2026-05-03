import React from 'react';
import { useCurrentFrame, useVideoConfig, spring, interpolate, AbsoluteFill } from 'remotion';
import type { ScenePlanItem } from '../../types';

interface KineticInsightProps {
  scene: ScenePlanItem;
  accentColor: string;
}

const TITLE_MAX_WORDS = 9;
const TITLE_LINE_MAX = 18;
const BULLET_MAX = 72;
const INSIGHT_MAX = 56;
const HARD_WORD_SPLIT = 14;

const cleanText = (value: string | null | undefined): string => {
  const safe = String(value ?? '')
    .replace(/\b(null|undefined|nan)\b/gi, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!safe) return '';
  return safe.replace(/\.{3,}/g, '…');
};

const clampByWords = (value: string, maxWords: number): string => {
  const words = cleanText(value).split(' ').filter(Boolean);
  if (words.length <= maxWords) return words.join(' ');
  return `${words.slice(0, maxWords).join(' ')}…`;
};

const clampByChars = (value: string, maxChars: number): string => {
  const safe = cleanText(value);
  if (safe.length <= maxChars) return safe;
  return `${safe.slice(0, maxChars - 1).trim()}…`;
};

const toTitleLines = (value: string): string[] => {
  const words = clampByWords(value, TITLE_MAX_WORDS).split(' ').filter(Boolean);
  if (words.length <= 4) return [words.join(' ')];

  const lines: string[] = [];
  let current = '';
  words.forEach((word) => {
    const candidate = current ? `${current} ${word}` : word;
    if (!current || candidate.length <= TITLE_LINE_MAX) {
      current = candidate;
      return;
    }
    lines.push(current);
    current = word;
  });
  if (current) lines.push(current);
  return lines.slice(0, 2);
};

const softenLongWords = (value: string): string => {
  const safe = cleanText(value);
  if (!safe) return '';
  return safe
    .split(' ')
    .map((word) => {
      if (word.length <= HARD_WORD_SPLIT) return word;
      const chunks = word.match(new RegExp(`.{1,${HARD_WORD_SPLIT}}`, 'g'));
      return (chunks || [word]).join('\u200B');
    })
    .join(' ');
};

const pickTitle = (scene: ScenePlanItem): string => {
  const fromTitle = cleanText(scene.title);
  if (fromTitle) return fromTitle;
  const titleLines = Array.isArray(scene.titleLines) ? scene.titleLines.map(cleanText).filter(Boolean) : [];
  if (titleLines.length > 0) return titleLines.join(' ');
  return cleanText(scene.keyword) || 'Ключевой вывод';
};

const pickBullets = (scene: ScenePlanItem): string[] => {
  const fromFacts = Array.isArray(scene.facts) ? scene.facts : [];
  const fromSteps = Array.isArray(scene.steps) ? scene.steps : [];
  const source = [...fromFacts, ...fromSteps]
    .map((item) => softenLongWords(clampByChars(item, BULLET_MAX)))
    .filter(Boolean);
  return source.slice(0, 2);
};

const pickBottomLine = (scene: ScenePlanItem): string => {
  const text = cleanText(scene.insight) || cleanText(scene.cta);
  return softenLongWords(clampByChars(text, INSIGHT_MAX));
};

export const KineticInsight: React.FC<KineticInsightProps> = ({ scene, accentColor }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const titleLines = toTitleLines(pickTitle(scene)).map(softenLongWords);
  const bullets = pickBullets(scene);
  const bottomLine = pickBottomLine(scene);

  const titleEntry = spring({ fps, frame: frame - 4, config: { damping: 16, stiffness: 130 } });
  const bottomEntry = spring({ fps, frame: frame - 20, config: { damping: 18, stiffness: 110 } });

  return (
    <AbsoluteFill style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'flex-start',
      padding: '86px 110px 140px',
    }}>
      <AbsoluteFill
        style={{
          background:
            'linear-gradient(180deg, rgba(7, 10, 18, 0.56) 0%, rgba(7, 10, 18, 0.38) 42%, rgba(7, 10, 18, 0.62) 100%)',
          pointerEvents: 'none',
        }}
      />

      <div
        style={{
          width: '100%',
          maxWidth: 1460,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'flex-start',
          gap: 22,
        }}
      >
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-start',
        gap: 10,
        width: '100%',
      }}>
        {titleLines.map((line, idx) => (
          <div
            key={idx}
            style={{
              fontFamily: '"Inter", "Montserrat", sans-serif',
              fontSize: 128,
              fontWeight: 900,
              color: idx === 0 ? accentColor : '#ffffff',
              lineHeight: 0.9,
              letterSpacing: '-0.04em',
              opacity: titleEntry,
              transform: `translateY(${interpolate(titleEntry, [0, 1], [18, 0])}px)`,
              textShadow: '0 10px 28px rgba(0, 0, 0, 0.45)',
              overflowWrap: 'anywhere',
              wordBreak: 'break-word',
            }}
          >
            {line}
          </div>
        ))}
      </div>

      {bullets.length > 0 && (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 24,
          marginTop: 18,
          maxWidth: 1240,
        }}>
          {bullets.map((fact, i) => {
            const rowEntry = spring({
              fps,
              frame: frame - 14 - i * 6,
              config: { damping: 20, stiffness: 120 },
            });
            return (
              <div key={i} style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 18,
              opacity: interpolate(rowEntry, [0, 1], [0, 1]),
              transform: `translateX(${interpolate(rowEntry, [0, 1], [-24, 0])}px)`,
            }}>
              <div style={{ width: 10, height: 10, marginTop: 18, borderRadius: '50%', background: accentColor }} />
              <div style={{
                fontFamily: '"Inter", "Montserrat", sans-serif',
                fontSize: 56,
                fontWeight: 500,
                color: 'white',
                lineHeight: 1.1,
                letterSpacing: '-0.02em',
                opacity: 0.92,
                overflowWrap: 'anywhere',
                wordBreak: 'break-word',
              }}>
                {fact}
              </div>
            </div>
            );
          })}
        </div>
      )}

      {bottomLine && (
        <div style={{
          position: 'absolute',
          bottom: 74,
          left: '50%',
          transform: `translateX(-50%) translateY(${interpolate(bottomEntry, [0, 1], [12, 0])}px)`,
          backgroundColor: 'rgba(18, 18, 26, 0.62)',
          padding: '16px 28px',
          borderRadius: 18,
          border: `1px solid rgba(255, 215, 0, 0.22)`,
          backdropFilter: 'blur(10px)',
          fontFamily: '"Inter", "Montserrat", sans-serif',
          fontSize: 48,
          fontWeight: 600,
          color: 'white',
          lineHeight: 1.1,
          letterSpacing: '-0.01em',
          maxWidth: 1240,
          opacity: bottomEntry,
          textAlign: 'center',
          boxShadow: '0 12px 24px rgba(0, 0, 0, 0.32)',
          overflowWrap: 'anywhere',
          wordBreak: 'break-word',
        }}>
          {bottomLine}
        </div>
      )}
      </div>

    </AbsoluteFill>
  );
};
