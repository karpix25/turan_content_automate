import React from 'react';

type ProjectCarouselImagePromptProps = {
  value: string;
  onChange: (value: string) => void;
};

export const ProjectCarouselImagePrompt: React.FC<ProjectCarouselImagePromptProps> = ({ value, onChange }) => (
  <div className="tg-card p-4">
    <div className="flex items-center justify-between gap-3 mb-2">
      <div>
        <h3 className="text-[15px] font-bold text-slate-900">Инструкции для картинок карусели</h3>
        <p className="text-[11px] text-slate-500 mt-1">Добавляются в общий мастер-промт всех слайдов проекта</p>
      </div>
      <span className="text-[11px] text-slate-400 shrink-0">{value.length}/2000</span>
    </div>
    <label htmlFor="carousel-image-prompt" className="sr-only">Инструкции для картинок карусели</label>
    <textarea
      id="carousel-image-prompt"
      value={value}
      maxLength={2000}
      rows={4}
      onChange={event => onChange(event.target.value)}
      placeholder="Например: светлый минималистичный фон, единая зелёная палитра, больше воздуха вокруг текста"
      className="input-field w-full min-h-[104px] resize-y text-sm leading-relaxed"
    />
  </div>
);
