import React from 'react';
import { UniqueizationMode } from '../../../types';

const UNIQUEIZATION_OPTIONS: Array<{
  value: UniqueizationMode;
  label: string;
  description: string;
}> = [
  {
    value: 'auto',
    label: 'Авто',
    description: 'Усиливает до Standard при дублях одной соцсети.',
  },
  {
    value: 'light',
    label: 'Light',
    description: 'Мягкие цветовые и технические отличия.',
  },
  {
    value: 'standard',
    label: 'Standard',
    description: 'Баланс уникальности и незаметных изменений.',
  },
  {
    value: 'aggressive',
    label: 'Aggressive',
    description: 'Максимальные отличия для рискованных публикаций.',
  },
  {
    value: 'off',
    label: 'Off',
    description: 'Без дополнительной уникализации.',
  },
];

type UniqueizationModeSelectorProps = {
  mode: UniqueizationMode;
  disabled: boolean;
  onChange: (mode: UniqueizationMode) => void;
};

export const UniqueizationModeSelector: React.FC<UniqueizationModeSelectorProps> = ({
  mode,
  disabled,
  onChange,
}) => {
  const activeOption = UNIQUEIZATION_OPTIONS.find(option => option.value === mode) ?? UNIQUEIZATION_OPTIONS[0];

  return (
    <div className="rounded-2xl border border-slate-100 bg-slate-50 p-3 space-y-3">
      <div>
        <p className="text-[11px] font-bold text-[#707579] uppercase tracking-wider">
          Уникализация видео
        </p>
        <p className="text-xs text-slate-500 mt-1 leading-relaxed">
          Auto усиливает до Standard при дублях одной соцсети.
        </p>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
        {UNIQUEIZATION_OPTIONS.map(option => {
          const isActive = option.value === mode;
          const className = [
            'h-9 rounded-xl text-xs font-bold border transition-all disabled:cursor-default',
            isActive
              ? 'bg-[#24a1de] border-[#24a1de] text-white shadow-sm shadow-blue-500/20'
              : 'bg-white border-slate-200 text-slate-600 hover:border-[#24a1de] hover:text-[#24a1de]',
          ].join(' ');

          return (
            <button
              key={option.value}
              type="button"
              onClick={() => onChange(option.value)}
              disabled={disabled || isActive}
              title={option.description}
              className={className}
            >
              {option.label}
            </button>
          );
        })}
      </div>

      <p className="text-[11px] text-slate-500 leading-relaxed">
        Сейчас выбран: <span className="font-bold text-slate-700">{activeOption.label}</span>. {activeOption.description}
      </p>
    </div>
  );
};
