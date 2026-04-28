import {useEffect, useMemo, useState} from 'react';
import {
  AbsoluteFill,
  OffthreadVideo,
  cancelRender,
  continueRender,
  delayRender,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {getTheme} from './montage/theme';
import type {AutoMontageProps, ScenePlanItem, WordCue} from './montage/types';
import {
  getLayoutForMoment,
  getLayoutSegmentStartSec,
  getMontageRules,
} from './montage/youtube-rules';
import {FullSlide} from './montage/components/FullSlide';

type LoadedData = {
  scenes: ScenePlanItem[];
  wordCueGroups: WordCue[][];
};

type ActiveSceneMatch = {
  index: number;
  scene: ScenePlanItem;
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
  themePreset,
  montagePreset,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const timeSec = frame / fps;

  const {scenes} = useLoadedData(scenePlanFile, wordCuesFile);
  const activeMatch = useMemo(() => getSceneAtTime(scenes, timeSec), [scenes, timeSec]);

  const theme = getTheme(themePreset);
  const rules = getMontageRules(montagePreset);

  const showOverlay = activeMatch !== null;
  const {scene: activeScene, index: activeSceneIndex} = activeMatch ?? {
    scene: scenes[0] ?? ({} as ScenePlanItem),
    index: 0,
  };

  const sceneStartFrame = activeScene?.start ? Math.floor(activeScene.start * fps) : 0;
  const inSceneFrame = Math.max(0, frame - sceneStartFrame);
  const timeInSceneSec = Math.max(0, timeSec - (activeScene?.start ?? 0));

  const layout =
    activeScene?.start !== undefined
      ? getLayoutForMoment(activeScene, activeSceneIndex, timeInSceneSec, montagePreset)
      : 'clean';

  const layoutStartSec =
    activeScene?.start !== undefined
      ? getLayoutSegmentStartSec(activeScene, timeInSceneSec, montagePreset)
      : 0;
  const inLayoutFrame = Math.max(0, inSceneFrame - Math.floor(layoutStartSec * fps));

  // Panel entrance spring
  const layoutIn = spring({
    fps,
    frame: Math.floor(inLayoutFrame * 2.2),
    config: {damping: 22, stiffness: 140, mass: 0.8},
  });
  const panelOpacity = interpolate(layoutIn, [0, 1], [0, 1]);

  // Per-scene accent color
  const accentColor = theme.accent;

  return (
    <AbsoluteFill style={{backgroundColor: '#000'}}>
      {/* Background video */}
      {videoFile && (
        <OffthreadVideo
          src={staticFile(videoFile)}
          style={{width: '100%', height: '100%', objectFit: 'cover'}}
        />
      )}

      {/* FULL: typography overlay */}
      {showOverlay && (
        <AbsoluteFill>
          <FullSlide scene={activeScene} />
        </AbsoluteFill>
      )}
    </AbsoluteFill>
  );
};
