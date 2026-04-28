import {Composition} from 'remotion';
import {AutoMontage} from './AutoMontage';
import {defaultAutoMontageProps} from './montage/default-props';

const FPS = 30;

const getDurationInFrames = (props: typeof defaultAutoMontageProps): number => {
  const fallback = Math.ceil(defaultAutoMontageProps.durationSec * FPS);

  if (!Number.isFinite(props.durationSec) || props.durationSec <= 0) {
    return fallback;
  }

  return Math.max(FPS, Math.ceil(props.durationSec * FPS));
};

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="AutoMontage"
      component={AutoMontage}
      defaultProps={defaultAutoMontageProps}
      fps={FPS}
      width={1920}
      height={1080}
      durationInFrames={Math.ceil(defaultAutoMontageProps.durationSec * FPS)}
      calculateMetadata={({props}) => ({
        durationInFrames: getDurationInFrames(props),
      })}
    />
  );
};
