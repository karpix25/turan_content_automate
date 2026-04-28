import type {CSSProperties} from 'react';
import type {ScenePlanItem} from './types';

export const clamp = (value: number): number => Math.max(0, Math.min(1, value));

export const normalizeText = (value: string | undefined | null): string =>
  (value ?? '')
    .replace(/\s+/g, ' ')
    .replace(/\u00A0/g, ' ')
    .trim();


export const pickFirstText = (...values: Array<string | undefined | null>): string => {
  for (const value of values) {
    const normalized = normalizeText(value);
    if (normalized) {
      return normalized;
    }
  }

  return '';
};

export const splitAccentWord = (value: string): {lead: string; accent: string} => {
  const normalized = normalizeText(value);
  if (!normalized) {
    return {lead: '', accent: 'Фокус'};
  }

  const words = normalized.split(' ');
  if (words.length === 1) {
    return {lead: '', accent: words[0]};
  }

  return {
    lead: words.slice(0, -1).join(' '),
    accent: words[words.length - 1],
  };
};

export const lineClampStyle = (lines: number): CSSProperties => ({
  display: '-webkit-box',
  WebkitBoxOrient: 'vertical',
  WebkitLineClamp: lines,
  overflow: 'hidden',
});

export const smartSplitText = (text: string, maxWords: number = 4): {top: string; bottom: string} => {
  const clean = (text || '').trim();
  const words = clean.split(/\s+/);
  if (words.length <= maxWords && clean.length <= 35) return {top: clean, bottom: ''};
  
  // Try to find a good split point
  const top = words.slice(0, maxWords).join(' ');
  const bottom = words.slice(maxWords).join(' ');
  return {top, bottom};
};

export const buildHeroLines = (
  scene: ScenePlanItem | null,
  fallbackPrimary: string,
  fallbackSecondary: string,
): {primary: string; secondary: string} => {
  if (!scene) {
    return {
      primary: fallbackPrimary,
      secondary: fallbackSecondary,
    };
  }

  const safeTitles = Array.isArray(scene.titleLines) ? scene.titleLines : [];
  const rawPrimary = pickFirstText(safeTitles[0], scene.keyword, fallbackPrimary);
  const {top, bottom} = smartSplitText(rawPrimary, 4);

  const rawSecondary = bottom || pickFirstText(safeTitles[1], scene.insight, scene.cta, fallbackSecondary);

  return {
    primary: top,
    secondary: rawSecondary,
  };
};

export type IconPick = {
  icon: string;
  label: string;
};

export const ICON_RULES: Array<{icon: string; label: string; markers: string[]}> = [
  {icon: '💼', label: 'Бизнес', markers: ['бизнес', 'компан', 'предприним']},
  {icon: '📑', label: 'Тендеры', markers: ['тендер', 'госконтракт', 'закуп']},
  {icon: '📊', label: 'Аналитика', markers: ['цифр', 'данн', 'метрик', 'показател', 'сравн']},
  {icon: '💰', label: 'Деньги', markers: ['выручк', 'прибыл', 'маржа', 'руб', 'млн', 'млрд']},
  {icon: '🧾', label: 'Налоги', markers: ['налог', 'ндс', 'реформ']},
  {icon: '⚠️', label: 'Риски', markers: ['ошиб', 'риск', 'штраф']},
  {icon: '🤖', label: 'Технологии', markers: ['ии', 'интеллект', 'алгоритм', 'автомат']},
];

export const pickSceneIcon = (scene: ScenePlanItem): IconPick => {
  const safeTitles = Array.isArray(scene.titleLines) ? scene.titleLines : [];
  const safeSteps = Array.isArray(scene.steps) ? scene.steps : [];

  const text = [scene.keyword, scene.insight, scene.cta, ...safeTitles, ...safeSteps]
    .join(' ')
    .toLowerCase();

  for (const rule of ICON_RULES) {
    if (rule.markers.some((marker) => text.includes(marker))) {
      return {icon: rule.icon, label: rule.label};
    }
  }

  return {icon: '💡', label: 'Ключевая мысль'};
};

export const makeInfographicBars = (
  scene: ScenePlanItem,
  maxBars: number,
): Array<{label: string; value: number}> => {
  if (scene.bars && scene.bars.length > 0) {
    return scene.bars.slice(0, maxBars);
  }

  const steps = Array.isArray(scene.steps) ? scene.steps : [];
  const titleLines = Array.isArray(scene.titleLines) ? scene.titleLines : [];
  const pool = [scene.keyword, ...steps, ...titleLines].filter(Boolean);
  const unique: string[] = [];

  for (const item of pool) {
    const normalized = item.trim();
    if (!normalized) {
      continue;
    }
    if (unique.includes(normalized)) {
      continue;
    }
    unique.push(normalized);
  }

  return unique.slice(0, maxBars).map((label, index) => ({
    label: label, // Remove .slice(0, 18)
    value: clamp(0.86 - index * 0.14),
  }));
};

export type FeatureRow = {
  icon: string;
  title: string;
  description: string;
};

export const buildFeatureRows = ({
  scene,
  titleLines,
  steps,
  bars,
  sceneIcon,
  isData,
}: {
  scene: ScenePlanItem;
  titleLines: string[];
  steps: string[];
  bars: Array<{label: string; value: number}>;
  sceneIcon: IconPick;
  isData: boolean;
}): FeatureRow[] => {
  const barIcons = ['📊', '📈', '🧭'];
  const narrativeIcons = [sceneIcon.icon, '⚡', '🔍'];

  const dataRows: FeatureRow[] = bars.slice(0, 3).map((bar, index) => ({
    icon: barIcons[index] ?? '📌',
    title: bar.label,
    description: `Вклад: ${Math.round(clamp(bar.value) * 100)}%`,
  }));

  const narrativeRows: FeatureRow[] = [
    {
      icon: narrativeIcons[0],
      title: pickFirstText(scene.keyword, titleLines[0], 'Ключевой тезис'),
      description: pickFirstText(scene.insight, steps[0], scene.cta),
    },
    {
      icon: narrativeIcons[1],
      title: pickFirstText(titleLines[0], steps[0], scene.cta, 'Практика'),
      description: pickFirstText(steps[0], scene.cta, scene.insight),
    },
    {
      icon: narrativeIcons[2],
      title: pickFirstText(titleLines[1], steps[1], 'Сравнение'),
      description: pickFirstText(steps[1], scene.cta, scene.insight),
    },
  ];

  const ordered = isData ? [...dataRows, ...narrativeRows] : [...narrativeRows, ...dataRows];

  const unique: FeatureRow[] = [];
  const seen = new Set<string>();
  for (const item of ordered) {
    if (!item.title || !item.description) {
      continue;
    }

    const key = `${item.title}::${item.description}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    unique.push(item);
    if (unique.length === 4) {
      break;
    }
  }

  return unique;
};
