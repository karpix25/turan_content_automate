import React from 'react';
import { ChevronDown, Loader2 } from 'lucide-react';
import { PostMyPostProject, UniqueizationMode } from '../../../types';
import { UniqueizationModeSelector } from './UniqueizationModeSelector';

type PostMyPostProjectSelectorProps = {
  projects: PostMyPostProject[];
  selectedProjectId: number | null;
  loading: boolean;
  disabled: boolean;
  accountsCount: number;
  uniqueizationMode: UniqueizationMode;
  onUniqueizationModeChange: (mode: UniqueizationMode) => void;
  onChange: (projectId: number) => void;
};

export const PostMyPostProjectSelector: React.FC<PostMyPostProjectSelectorProps> = ({
  projects,
  selectedProjectId,
  loading,
  disabled,
  accountsCount,
  uniqueizationMode,
  onUniqueizationModeChange,
  onChange,
}) => {
  const selectedProject = projects.find(project => project.id === selectedProjectId);

  return (
    <div className="tg-card p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-bold text-[#707579] uppercase tracking-wider">Контейнер PostMyPost</p>
          <h3 className="text-base font-bold text-slate-900 mt-1">
            {selectedProject?.name || 'Выберите проект'}
          </h3>
          <p className="text-xs text-slate-500 mt-1">
            Внутри контейнера показываются только подключённые к нему аккаунты.
          </p>
        </div>
        <span className="px-2.5 py-1 rounded-full bg-blue-50 text-[#24a1de] text-[11px] font-bold whitespace-nowrap">
          {accountsCount} аккаунт{accountsCount === 1 ? '' : 'ов'}
        </span>
      </div>

      <div className="relative">
        <select
          value={selectedProjectId ?? ''}
          onChange={(event) => onChange(Number(event.target.value))}
          disabled={disabled || loading || projects.length === 0}
          className="input-field h-11 appearance-none pr-10 text-sm font-semibold bg-white disabled:opacity-60"
        >
          <option value="" disabled>
            {loading ? 'Загружаю проекты...' : 'Выберите контейнер'}
          </option>
          {projects.map(project => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
        <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-slate-400">
          {loading ? <Loader2 size={16} className="animate-spin" /> : <ChevronDown size={16} />}
        </div>
      </div>

      <UniqueizationModeSelector
        mode={uniqueizationMode}
        disabled={disabled || loading || !selectedProjectId}
        onChange={onUniqueizationModeChange}
      />
    </div>
  );
};
