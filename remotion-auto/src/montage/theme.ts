import type {ThemePreset} from './types';

export type Theme = {
  fontMain: string;
  fontAccent: string;
  textMain: string;
  textMuted: string;
  accent: string;
  cta: string;
  bgOverlay: string;
  panel: string;
  panelStrong: string;
  insightGlow: string;
};

const THEMES: Record<ThemePreset, Theme> = {
  youtubeBusiness: {
    fontMain: '"Avenir Next", "Montserrat", sans-serif',
    fontAccent: '"Oswald", "Arial Narrow", sans-serif',
    textMain: '#F7F4FF',
    textMuted: '#D8D0EA',
    accent: '#7BD2FF',
    cta: '#FFC58B',
    bgOverlay:
      'linear-gradient(180deg, rgba(29, 14, 48, 0.08) 0%, rgba(29, 14, 48, 0.32) 55%, rgba(17, 10, 26, 0.56) 100%)',
    panel: 'rgba(22, 15, 34, 0.62)',
    panelStrong: 'rgba(16, 10, 26, 0.78)',
    insightGlow: 'rgba(123, 210, 255, 0.34)'
  },
  sunset: {
    fontMain: '"Avenir Next", "Montserrat", sans-serif',
    fontAccent: '"Bebas Neue", "Arial Narrow", sans-serif',
    textMain: '#FDF4EE',
    textMuted: '#FFD8C7',
    accent: '#FF6B4A',
    cta: '#FFD34D',
    bgOverlay: 'linear-gradient(170deg, rgba(18,10,18,0.1) 0%, rgba(18,10,18,0.65) 60%, rgba(0,0,0,0.82) 100%)',
    panel: 'rgba(12, 10, 16, 0.56)',
    panelStrong: 'rgba(10, 8, 14, 0.76)',
    insightGlow: 'rgba(255, 107, 74, 0.35)'
  },
  ocean: {
    fontMain: '"Avenir Next", "Montserrat", sans-serif',
    fontAccent: '"Bebas Neue", "Arial Narrow", sans-serif',
    textMain: '#ECFBFF',
    textMuted: '#C6ECF4',
    accent: '#4DD4FF',
    cta: '#9AFF7A',
    bgOverlay: 'linear-gradient(170deg, rgba(2, 18, 28, 0.15) 0%, rgba(2, 18, 28, 0.65) 60%, rgba(0,0,0,0.85) 100%)',
    panel: 'rgba(0, 22, 34, 0.54)',
    panelStrong: 'rgba(0, 15, 24, 0.76)',
    insightGlow: 'rgba(77, 212, 255, 0.34)'
  },
  amber: {
    fontMain: '"Avenir Next", "Montserrat", sans-serif',
    fontAccent: '"Bebas Neue", "Arial Narrow", sans-serif',
    textMain: '#FFF8E8',
    textMuted: '#FFE1B0',
    accent: '#FF8A1D',
    cta: '#FFF261',
    bgOverlay: 'linear-gradient(170deg, rgba(24, 15, 4, 0.08) 0%, rgba(24, 15, 4, 0.7) 58%, rgba(0,0,0,0.84) 100%)',
    panel: 'rgba(40, 22, 0, 0.56)',
    panelStrong: 'rgba(32, 17, 0, 0.78)',
    insightGlow: 'rgba(255, 138, 29, 0.34)'
  }
};

export const getTheme = (preset: ThemePreset): Theme => THEMES[preset] ?? THEMES.youtubeBusiness;
