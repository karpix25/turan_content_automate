import type {AutoMontageProps} from './types';

export const defaultAutoMontageProps: AutoMontageProps = {
  videoFile: 'input/source.mp4',
  scenePlanFile: 'input/scene-plan.generated.json',
  wordCuesFile: 'input/scene-word-cues.generated.json',
  durationSec: 353.83,
  cueWindowSec: 0.95,
  themePreset: 'youtubeBusiness',
  montagePreset: 'balanced',
};
