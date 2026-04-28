export type SceneBar = {
  label: string;
  value: number; // 0.0 to 1.0
};

export type ChartType =
  | 'BIG_NUMBER'
  | 'DONUT'
  | 'BAR'
  | 'COMPARISON'
  | 'FLOW'
  | 'BENTO'
  | 'METRIC_CARDS';

export type LayoutPattern = 'CENTER' | 'SPLIT' | 'MODERN';

export type SceneMode =
  | 'face'
  | 'clean'
  | 'lower-third'
  | 'overlay'
  | 'chart'
  | 'insight'
  | 'full'
  | 'mini'
  | string;

export type ScenePlanItem = {
  start: number;
  end: number;
  mode?: SceneMode;
  // Legacy fields
  titleLines: string[];
  steps: string[];
  insight: string;
  cta: string;
  keyword: string;
  blockName?: string;
  bars?: SceneBar[];
  // New design system fields
  chartType?: ChartType;
  layoutPattern?: LayoutPattern;
  // Structured data for charts
  title?: string;        // Short hook title (2-4 words)
  subtitle?: string;     // Supporting context
  value?: number;        // Primary number (e.g. 90 for "90%")
  unit?: string;         // Unit string (e.g. "%" or "млн ₽")
  facts?: string[];      // 2-3 synthesized factual statements
};

export type WordCue = {
  time: number;
  text: string;
};

export type ThemePreset = 'youtubeBusiness' | 'sunset' | 'ocean' | 'amber';
export type MontagePreset = 'balanced' | 'calm' | 'data';

export type AutoMontageProps = {
  videoFile: string;
  scenePlanFile: string;
  wordCuesFile: string;
  durationSec: number;
  cueWindowSec: number;
  themePreset: ThemePreset;
  montagePreset: MontagePreset;
};

