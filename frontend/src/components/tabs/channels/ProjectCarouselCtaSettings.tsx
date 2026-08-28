import React from 'react';

type Props = {
  platforms: string[];
  carouselCtas: Record<string, string>;
  storyCtas: Record<string, string>;
  onCarouselChange: (platform: string, value: string) => void;
  onStoryChange: (platform: string, value: string) => void;
};

const LABELS: Record<string, string> = {
  instagram: 'Instagram',
  tiktok: 'TikTok',
  vk: 'ВКонтакте',
  telegram: 'Telegram',
};

export const ProjectCarouselCtaSettings: React.FC<Props> = ({
  platforms,
  carouselCtas,
  storyCtas,
  onCarouselChange,
  onStoryChange,
}) => (
  <div className="tg-card p-4 space-y-3">
    <div>
      <h3 className="text-[15px] font-bold text-slate-900">CTA для каруселей и историй</h3>
      <p className="text-[11px] text-slate-500 mt-1">
        Один CTA на социальную сеть проекта. У одинаковых профилей сети CTA общий.
      </p>
    </div>
    {(platforms.length ? platforms : ['instagram', 'tiktok', 'vk', 'telegram']).map(platform => (
      <div key={platform} className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <label className="text-xs font-bold text-[#707579] uppercase tracking-wider">
          {LABELS[platform] || platform} — карусель
          <input
            value={carouselCtas[platform] || ''}
            onChange={event => onCarouselChange(platform, event.target.value)}
            placeholder="Например: Сохрани пост и подпишись"
            className="input-field h-10 w-full mt-2 text-sm normal-case"
          />
        </label>
        <label className="text-xs font-bold text-[#707579] uppercase tracking-wider">
          {LABELS[platform] || platform} — история
          <input
            value={storyCtas[platform] || ''}
            onChange={event => onStoryChange(platform, event.target.value)}
            placeholder="Например: Напиши нам в директ"
            className="input-field h-10 w-full mt-2 text-sm normal-case"
          />
        </label>
      </div>
    ))}
  </div>
);
