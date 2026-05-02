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
import type {AutoMontageProps, ScenePlanItem} from './montage/types';
import {BlockOpener} from './montage/components/BlockOpener';

type LoadedData = {
  scenes: ScenePlanItem[];
};

type ActiveSceneMatch = {
  index: number;
  scene: ScenePlanItem;
};

const normalizeText = (value: string | undefined | null): string =>
  String(value || '').replace(/\s+/g, ' ').trim();

const trimOpener = (value: string): string => {
  const clean = normalizeText(value).replace(/["'«»]+/g, '').trim();
  if (!clean) return '';
  const words = clean.split(' ');
  return words.length > 6 ? words.slice(0, 6).join(' ') : clean;
};

const pickSceneOpener = (scene: ScenePlanItem | undefined): string => {
  if (!scene) return '';
  const openerField = trimOpener(normalizeText(scene.chapterOpener || scene.opener));
  if (openerField) return openerField;
  const candidates = [
    normalizeText(scene.chapterTitle),
    normalizeText(scene.title),
    normalizeText(scene.keyword),
    ...((scene.titleLines || []).map(normalizeText)),
    normalizeText(scene.insight),
    normalizeText(scene.cta),
  ].filter(Boolean);
  const base = candidates[0] || '';
  if (!base) return '';
  return trimOpener(base);
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
        const [sceneRes] = await Promise.all([fetch(staticFile(scenePlanFile))]);
        if (!sceneRes.ok) throw new Error(`Cannot read scene plan: ${scenePlanFile}`);

        const scenes = (await sceneRes.json()) as ScenePlanItem[];
        if (canceled) return;
        setData({scenes});
        continueRender(handle);
      } catch (error) {
        cancelRender(error);
      }
    };
    load();
    return () => {
      canceled = true;
    };
  }, [scenePlanFile, handle]);

  if (!data) return {scenes: []};
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

  const {scenes} = useLoadedData(scenePlanFile, wordCuesFile);
  const activeMatch = useMemo(() => getSceneAtTime(scenes, timeSec), [scenes, timeSec]);

  const showOverlay = activeMatch !== null;
  const {scene: activeScene} = activeMatch ?? {
    scene: scenes[0] ?? ({} as ScenePlanItem),
    index: 0,
  };

  const openerStartFrame = useMemo(() => {
    const start = Number(activeScene?.start ?? 0);
    if (!Number.isFinite(start) || start <= 0) return 0;
    return Math.floor(start * fps);
  }, [activeScene, fps]);

  const inBlockFrame = Math.max(0, frame - openerStartFrame);
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
          <BlockOpener text={openerText} visibleFrames={openerFrames} sceneFrame={inBlockFrame} />
        </>
      )}
    </AbsoluteFill>
  );
};
