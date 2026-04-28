import type {MontagePreset, SceneMode, ScenePlanItem} from './types';

export type MontageLayout = 'clean' | 'overlay' | 'full';

type PresetRules = {
  cleanSegmentSec: number;
  overlaySegmentSec: number;
  fullSegmentSec: number; // Max 5s recommended
  maxTitleLines: number;
  maxSteps: number;
  maxBars: number;
  maxCueWords: number;
  openingSec: number;
};

const PRESET_RULES: Record<MontagePreset, PresetRules> = {
  balanced: {
    cleanSegmentSec: 7,
    overlaySegmentSec: 8,
    fullSegmentSec: 8, 
    maxTitleLines: 3,
    maxSteps: 2,
    maxBars: 4,
    maxCueWords: 3,
    openingSec: 10,
  },
  calm: {
    cleanSegmentSec: 10,
    overlaySegmentSec: 10,
    fullSegmentSec: 8,
    maxTitleLines: 2,
    maxSteps: 2,
    maxBars: 3,
    maxCueWords: 2,
    openingSec: 10,
  },
  data: {
    cleanSegmentSec: 5,
    overlaySegmentSec: 6,
    fullSegmentSec: 10, 
    maxTitleLines: 3,
    maxSteps: 2,
    maxBars: 4,
    maxCueWords: 3,
    openingSec: 10,
  },
};

export const getMontageRules = (preset: MontagePreset): PresetRules => {
  return PRESET_RULES[preset] ?? PRESET_RULES.balanced;
};

const mapModeToLayout = (mode: SceneMode | undefined): MontageLayout | null => {
  if (!mode) return null;
  const m = mode.toLowerCase();
  if (m === 'face' || m === 'clean') return 'clean';
  if (m === 'lower-third' || m === 'overlay' || m === 'mini') return 'overlay';
  if (m === 'chart' || m === 'insight' || m === 'full') return 'full';
  return null;
};

const DATA_MARKERS = [
  'цифр',
  'данн',
  'ошиб',
  'пример',
  'сравн',
  'факт',
  'процент',
  'метрик',
  'показател',
  'тендер',
  'выручк',
  'маржа',
  'kpi',
  'руб',
  'млн',
  'млрд',
];

export const isDataScene = (scene: ScenePlanItem): boolean => {
  const safeTitles = Array.isArray(scene.titleLines) ? scene.titleLines : [];
  const safeSteps = Array.isArray(scene.steps) ? scene.steps : [];

  const combined = [
    scene.keyword,
    scene.insight,
    scene.cta,
    ...safeTitles,
    ...safeSteps,
  ]
    .join(' ')
    .toLowerCase();

  if (/\d/.test(combined)) {
    return true;
  }

  return DATA_MARKERS.some((marker) => combined.includes(marker));
};

export const getLayoutForMoment = (
  scene: ScenePlanItem,
  sceneIndex: number,
  timeInSceneSec: number,
  preset: MontagePreset,
): MontageLayout => {
  // 1. Respect explicit mode from JSON (LLM decision)
  if (scene.mode) {
    const m = scene.mode.toLowerCase();
    if (m === 'mini' || m === 'overlay' || m === 'lower-third') return 'overlay';
    if (m === 'full' || m === 'chart' || m === 'insight') return 'full';
    if (m === 'clean' || m === 'face') return 'clean';
  }

  // 2. Fall back to time-based cycle
  const rules = getMontageRules(preset);
  const cycle = rules.cleanSegmentSec + rules.overlaySegmentSec + rules.fullSegmentSec;
  const local = ((timeInSceneSec % cycle) + cycle) % cycle;

  if (local < rules.cleanSegmentSec) {
    return 'clean';
  }

  if (local < rules.cleanSegmentSec + rules.overlaySegmentSec) {
    return 'overlay';
  }

  return 'full';
};


export const getLayoutSegmentStartSec = (
  scene: ScenePlanItem,
  timeInSceneSec: number,
  preset: MontagePreset,
): number => {
  const rules = getMontageRules(preset);
  const cycle = rules.cleanSegmentSec + rules.overlaySegmentSec + rules.fullSegmentSec;
  const cycleStart = Math.floor(timeInSceneSec / cycle) * cycle;
  const local = timeInSceneSec - cycleStart;

  if (local < rules.cleanSegmentSec) {
    return cycleStart;
  }

  if (local < rules.cleanSegmentSec + rules.overlaySegmentSec) {
    return cycleStart + rules.cleanSegmentSec;
  }

  return cycleStart + rules.cleanSegmentSec + rules.overlaySegmentSec;
};
