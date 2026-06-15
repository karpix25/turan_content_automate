import React from 'react';

type Props = {
  previewUrl: string;
  xPercent: number;
  yPercent: number;
  sizePercent: number;
  opacityPercent: number;
  onXChange: (value: number) => void;
  onYChange: (value: number) => void;
  onSizeChange: (value: number) => void;
  onOpacityChange: (value: number) => void;
};

const controls = [
  { key: 'x', label: 'Горизонталь', min: 0, max: 100 },
  { key: 'y', label: 'Вертикаль', min: 0, max: 100 },
  { key: 'size', label: 'Размер', min: 5, max: 100 },
  { key: 'opacity', label: 'Прозрачность', min: 0, max: 100 },
] as const;

export const AvatarOverlayPositionControl: React.FC<Props> = ({
  previewUrl,
  xPercent,
  yPercent,
  sizePercent,
  opacityPercent,
  onXChange,
  onYChange,
  onSizeChange,
  onOpacityChange,
}) => {
  const valueByKey = {
    x: xPercent,
    y: yPercent,
    size: sizePercent,
    opacity: opacityPercent,
  };
  const setterByKey = {
    x: onXChange,
    y: onYChange,
    size: onSizeChange,
    opacity: onOpacityChange,
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-4 mb-3">
      <div className="rounded-xl border border-slate-200 bg-slate-100 p-2">
        <p className="text-[11px] font-bold uppercase tracking-wider text-slate-500 mb-2">Превью слоя</p>
        <div className="relative mx-auto aspect-[9/16] max-h-[360px] overflow-hidden rounded-lg bg-gradient-to-b from-slate-200 to-slate-100">
          {previewUrl ? (
            <video
              src={previewUrl}
              className="absolute object-contain"
              style={{
                height: `${sizePercent}%`,
                left: `${xPercent}%`,
                top: `${yPercent}%`,
                opacity: opacityPercent / 100,
                transform: `translate(-${xPercent}%, -${yPercent}%)`,
              }}
              muted
              loop
              autoPlay
              playsInline
            />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center px-4 text-center text-xs font-semibold text-slate-500">
              Загрузите прозрачный WEBM/MOV для превью
            </div>
          )}
        </div>
      </div>
      <div className="rounded-xl border border-slate-200 bg-white p-3">
        <p className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-3">Позиция аватара в ролике</p>
        {controls.map((control) => (
          <label key={control.key} className="block mb-3 last:mb-0">
            <div className="mb-1 flex items-center justify-between text-xs font-semibold text-slate-500">
              <span>{control.label}</span>
              <span>{valueByKey[control.key]}</span>
            </div>
            <input
              type="range"
              min={control.min}
              max={control.max}
              value={valueByKey[control.key]}
              onChange={(event) => setterByKey[control.key](Number(event.target.value))}
              className="w-full accent-[#24a1de]"
            />
          </label>
        ))}
      </div>
    </div>
  );
};
