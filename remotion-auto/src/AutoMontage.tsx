import {useEffect, useMemo, useState} from 'react';
import {
  AbsoluteFill,
  OffthreadVideo,
  cancelRender,
  continueRender,
  delayRender,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import type {AutoMontageProps, ScenePlanItem, WordCue} from './montage/types';
import {BottomCaption} from './montage/components/BottomCaption';
import {BlockOpener} from './montage/components/BlockOpener';

type LoadedData = {
  scenes: ScenePlanItem[];
  wordCueGroups: WordCue[][];
};

type ActiveSceneMatch = {
  index: number;
  scene: ScenePlanItem;
};

const normalizeText = (value: string | undefined | null): string =>
  String(value || '').replace(/\s+/g, ' ').trim();

const pickSceneOpener = (scene: ScenePlanItem | undefined): string => {
  if (!scene) return '';
  const candidates = [
    ...((scene.titleLines || []).map(normalizeText)),
    normalizeText(scene.insight),
    normalizeText(scene.title),
    normalizeText(scene.keyword),
    normalizeText(scene.cta),
  ].filter(Boolean);
  const base = candidates[0] || '';
  if (!base) return '';
  const words = base.split(' ');
  const shortened = words.length > 14 ? words.slice(0, 14).join(' ') : base;
  return shortened.endsWith('.') || shortened.endsWith('!') || shortened.endsWith('?')
    ? shortened
    : `${shortened}.`;
};

const normalizeCaptionText = (value: string): string =>
  value
    .replace(/\s+([,.:;!?])/g, '$1')
    .replace(/[“”"]/g, '')
    .replace(/\s+/g, ' ')
    .trim();

const buildBottomCaption = (cueWords: WordCue[], timeSec: number): string => {
  if (!cueWords || cueWords.length === 0) return '';
  const currentIndex = cueWords.findIndex((item) => item.time > timeSec + 0.02);
  const startIndex = currentIndex <= 0 ? 0 : Math.max(0, currentIndex - 1);
  const slice = cueWords.slice(startIndex, Math.min(cueWords.length, startIndex + 8));
  if (slice.length === 0) return '';
  const sentenceWords: string[] = [];
  for (const cue of slice) {
    const token = String(cue.text || '').trim();
    if (!token) continue;
    sentenceWords.push(token);
    if (/[.!?…]$/.test(token)) break;
  }
  const normalized = normalizeCaptionText(sentenceWords.join(' '));
  return normalized;
};

const getSceneAtTime = (scenes: ScenePlanItem[], timeSec: number): ActiveSceneMatch | null => {
  if (scenes.length === 0) return null;
  const foundIndex = scenes.findIndex((s) => timeSec >= s.start && timeSec < s.end);
  if (foundIndex >= 0) return {index: foundIndex, scene: scenes[foundIndex]};
  return null;
};

const useLoadedData = (scenePlanFile: string, wordCuesFile: string): LoadedData => {
  const [data, setData] = useState<LoadedData | null>(null);
  const [handle] = useState(() => delayRender('Loading scene plan...'));

  useEffect(() => {
    let canceled = false;
    const load = async () => {
      try {
        const [sceneRes, cuesRes] = await Promise.all([
          fetch(staticFile(scenePlanFile)),
          fetch(staticFile(wordCuesFile)),
        ]);
        if (!sceneRes.ok) throw new Error(`Cannot read scene plan: ${scenePlanFile}`);
        if (!cuesRes.ok) throw new Error(`Cannot read word cues: ${wordCuesFile}`);

        const scenes = (await sceneRes.json()) as ScenePlanItem[];
        const wordCueGroups = (await cuesRes.json()) as WordCue[][];
        if (canceled) return;
        setData({scenes, wordCueGroups});
        continueRender(handle);
      } catch (error) {
        cancelRender(error);
      }
    };
    load();
    return () => {
      canceled = true;
    };
  }, [scenePlanFile, wordCuesFile, handle]);

  if (!data) return {scenes: [], wordCueGroups: []};
  return data;
};

export const AutoMontage: React.FC<AutoMontageProps> = ({
  videoFile,
  scenePlanFile,
  wordCuesFile,
  themePreset: _themePreset,
  montagePreset: _montagePreset,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const timeSec = frame / fps;

  const {scenes, wordCueGroups} = useLoadedData(scenePlanFile, wordCuesFile);
  const activeMatch = useMemo(() => getSceneAtTime(scenes, timeSec), [scenes, timeSec]);

  const showOverlay = activeMatch !== null;
  const {scene: activeScene, index: activeSceneIndex} = activeMatch ?? {
    scene: scenes[0] ?? ({} as ScenePlanItem),
    index: 0,
  };

  const sceneStartFrame = activeScene?.start ? Math.floor(activeScene.start * fps) : 0;
  const inSceneFrame = Math.max(0, frame - sceneStartFrame);
  const cueWords = wordCueGroups[activeSceneIndex] || [];
  const bottomCaptionText = buildBottomCaption(cueWords, timeSec);
  const openerText = pickSceneOpener(activeScene);
  const openerFrames = Math.floor(3 * fps);

  return (
    <AbsoluteFill style={{backgroundColor: '#000'}}>
      {/* Background video */}
      {videoFile && (
        <OffthreadVideo
          src={staticFile(videoFile)}
          style={{width: '100%', height: '100%', objectFit: 'cover'}}
        />
      )}

      {/* Minimal overlay system: opener + bottom caption */}
      {showOverlay && (
        <>
          <BlockOpener text={openerText} visibleFrames={openerFrames} />
          <BottomCaption text={bottomCaptionText} />
        </>
      )}
    </AbsoluteFill>
  );
};
