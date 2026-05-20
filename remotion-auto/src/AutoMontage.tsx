import {useEffect, useMemo, useState} from 'react';
import {
  AbsoluteFill,
  OffthreadVideo,
  Sequence,
  cancelRender,
  continueRender,
  delayRender,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import type {AutoMontageProps, ScenePlanItem} from './montage/types';
import {BlockOpener} from './montage/components/BlockOpener';
import {ChapterBanner} from './montage/components/ChapterBanner';
import {FullSlide} from './montage/components/FullSlide';
import {MiniAccent} from './montage/components/MiniAccent';
import {getTheme} from './montage/theme';

type LoadedData = {
  scenes: ScenePlanItem[];
};

type ActiveSceneMatch = {
  index: number;
  scene: ScenePlanItem;
  displayStart: number;
  displayEnd: number;
};

const MIN_OVERLAY_SEC = 8;
const SCENE_GAP_SEC = 0.25;

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

const getSceneDisplayEnd = (scenes: ScenePlanItem[], index: number): number => {
  const scene = scenes[index];
  const start = Number(scene.start);
  const end = Number(scene.end);
  const rawEnd = Number.isFinite(end) && end > start ? end : start + MIN_OVERLAY_SEC;
  const minEnd = start + MIN_OVERLAY_SEC;
  const nextStart = Number(scenes[index + 1]?.start);
  const displayEnd = Math.max(rawEnd, minEnd);

  if (Number.isFinite(nextStart) && nextStart > start) {
    return Math.min(displayEnd, Math.max(start + 1, nextStart - SCENE_GAP_SEC));
  }

  return displayEnd;
};

const getSceneAtTime = (scenes: ScenePlanItem[], timeSec: number): ActiveSceneMatch | null => {
  if (scenes.length === 0) return null;
  const foundIndex = scenes.findIndex((s, index) => {
    const start = Number(s.start);
    if (!Number.isFinite(start)) return false;
    return timeSec >= start && timeSec < getSceneDisplayEnd(scenes, index);
  });
  if (foundIndex >= 0) {
    const scene = scenes[foundIndex];
    return {
      index: foundIndex,
      scene,
      displayStart: scene.start,
      displayEnd: getSceneDisplayEnd(scenes, foundIndex),
    };
  }
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
  themePreset,
  montagePreset: _montagePreset,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const timeSec = frame / fps;

  const {scenes} = useLoadedData(scenePlanFile, wordCuesFile);
  const activeMatch = useMemo(() => getSceneAtTime(scenes, timeSec), [scenes, timeSec]);
  const theme = getTheme(themePreset);

  const showOverlay = activeMatch !== null;
  const {scene: activeScene, index: activeSceneIndex, displayStart, displayEnd} = activeMatch ?? {
    scene: scenes[0] ?? ({} as ScenePlanItem),
    index: 0,
    displayStart: 0,
    displayEnd: 0,
  };

  const sceneStartFrame = useMemo(() => {
    const start = Number(displayStart ?? activeScene?.start ?? 0);
    if (!Number.isFinite(start) || start <= 0) return 0;
    return Math.floor(start * fps);
  }, [activeScene, displayStart, fps]);

  const sceneDurationFrames = Math.max(1, Math.ceil(Math.max(0, displayEnd - displayStart) * fps));
  const inSceneFrame = Math.max(0, frame - sceneStartFrame);
  const openerText = pickSceneOpener(activeScene);
  const openerFrames = Math.floor(3 * fps);
  const mode = String(activeScene?.mode || 'full').toLowerCase();
  const isMiniMode =
    mode === 'mini' ||
    mode === 'lower-third' ||
    mode === 'lower_third' ||
    mode === 'overlay' ||
    mode === 'side';
  const prevScene = activeSceneIndex > 0 ? scenes[activeSceneIndex - 1] : null;
  const currentChapter = Number(activeScene?.chapterIndex ?? activeSceneIndex + 1);
  const prevChapter = Number(prevScene?.chapterIndex ?? 0);
  const isChapterStart = activeSceneIndex === 0 || currentChapter !== prevChapter;

  return (
    <AbsoluteFill style={{backgroundColor: '#000'}}>
      {/* Background video */}
      {videoFile && (
        <OffthreadVideo
          src={staticFile(videoFile)}
          style={{width: '100%', height: '100%', objectFit: 'cover'}}
        />
      )}

      {showOverlay && (
        <Sequence from={sceneStartFrame} durationInFrames={sceneDurationFrames}>
          <AbsoluteFill>
            {isMiniMode ? (
              <MiniAccent scene={activeScene} accentColor={theme.accent} />
            ) : (
              <FullSlide scene={activeScene} />
            )}
            <ChapterBanner
              scene={activeScene}
              isChapterStart={isChapterStart}
              inSceneFrame={inSceneFrame}
            />
            <BlockOpener text={openerText} visibleFrames={openerFrames} sceneFrame={inSceneFrame} />
          </AbsoluteFill>
        </Sequence>
      )}
    </AbsoluteFill>
  );
};
