import React from 'react';
import { CarouselFormats } from '../../../types';

type Props = {
  platforms: string[];
  formats: CarouselFormats;
  disabled?: boolean;
  carouselCtas: Record<string, string>;
  storyCtas: Record<string, string>;
  onFormatChange: (platform: string, format: 'carousel' | 'story', enabled: boolean) => void;
  onCarouselChange: (platform: string, value: string) => void;
  onStoryChange: (platform: string, value: string) => void;
};

const LABELS: Record<string, string> = {
  instagram: 'Instagram', tiktok: 'TikTok', vk: 'ВКонтакте', telegram: 'Telegram',
};

export const ProjectCarouselCtaSettings: React.FC<Props> = ({
  platforms, formats, disabled, carouselCtas, storyCtas,
  onFormatChange, onCarouselChange, onStoryChange,
}) => (
  <div className="tg-card p-4 space-y-4">
    <div>
      <h3 className="text-[15px] font-bold text-slate-900">Карусели и сторис</h3>
      <p className="text-xs text-slate-500 mt-1">
        Выберите форматы для каждой соцсети. Настройки общие для её аккаунтов в проекте.
        CTA нужен только для включённых форматов.
      </p>
    </div>
    {!platforms.length && <p className="text-sm text-slate-500">Включите подключённый аккаунт, чтобы настроить форматы.</p>}
    {platforms.map(platform => (
      <fieldset key={platform} className="border border-slate-200 rounded-xl p-3" disabled={disabled}>
        <legend className="px-1 text-sm font-semibold text-slate-900">{LABELS[platform] || platform}</legend>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {(['carousel', 'story'] as const).map(format => {
            const supported = !(platform === 'tiktok' && format === 'story');
            const enabled = supported && (formats[platform]?.[format] ?? true);
            const label = format === 'carousel' ? 'Карусели' : 'Сторис';
            const inputId = `cta-${platform}-${format}`;
            return (
              <div key={format} className="space-y-2">
                <label className={`flex items-center justify-between gap-3 text-sm font-medium ${supported ? 'text-slate-800 cursor-pointer' : 'text-slate-400'}`}>
                  {label}
                  <span className="relative inline-flex shrink-0">
                  <input
                    type="checkbox"
                    role="switch"
                    aria-label={`${LABELS[platform] || platform}: ${label}`}
                    checked={enabled}
                    disabled={!supported || disabled}
                    onChange={event => onFormatChange(platform, format, event.target.checked)}
                    className="peer sr-only"
                  />
                  <span aria-hidden="true" className="h-6 w-11 rounded-full bg-slate-200 transition-colors peer-checked:bg-blue-600 peer-focus-visible:ring-2 peer-focus-visible:ring-blue-500 peer-focus-visible:ring-offset-2 peer-disabled:opacity-40" />
                  <span aria-hidden="true" className="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow-sm transition-transform peer-checked:translate-x-5 peer-disabled:opacity-60" />
                  </span>
                </label>
                {supported ? <>
                  <label htmlFor={inputId} className="block text-xs text-slate-500">Призыв к действию (CTA)</label>
                  <input
                    id={inputId}
                    value={(format === 'carousel' ? carouselCtas : storyCtas)[platform] || ''}
                    disabled={!enabled || disabled}
                    onChange={event => (format === 'carousel' ? onCarouselChange : onStoryChange)(platform, event.target.value)}
                    placeholder={format === 'carousel' ? 'Сохрани пост и подпишись' : 'Напиши нам в директ'}
                    className="input-field h-10 w-full text-sm disabled:opacity-40"
                  />
                </> : <p className="text-xs text-slate-400">Публикация сторис в TikTok не поддерживается.</p>}
              </div>
            );
          })}
        </div>
      </fieldset>
    ))}
    <p className="text-xs text-slate-500">
      Нажмите «Сохранить настройки», чтобы применить выбор к следующей генерации и постановке в расписание.
      Уже запланированные публикации не изменятся.
    </p>
  </div>
);
