import React from 'react';
import { ChevronDown, Loader2 } from 'lucide-react';
import { usePostMyPostProject } from '../../context/PostMyPostProjectContext';

export const ProjectSwitcherBar: React.FC = () => {
  const {
    projects,
    selectedProjectId,
    loading,
    savingProject,
    error,
    selectProject,
  } = usePostMyPostProject();

  return (
    <div className="sticky top-[57px] z-40 bg-[#f1f2f6]/95 backdrop-blur border-b border-slate-200/70 px-4 py-1.5">
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-bold text-slate-400 uppercase shrink-0">Проект</span>
        <div className="relative min-w-0 flex-1">
          <select
            value={selectedProjectId ?? ''}
            onChange={(event) => selectProject(Number(event.target.value))}
            disabled={loading || savingProject || projects.length === 0}
            className="w-full h-8 appearance-none rounded-lg border border-slate-200 bg-white pl-2.5 pr-8 text-xs font-bold text-slate-800 outline-none disabled:opacity-60"
          >
            <option value="" disabled>
              {loading ? 'Загружаю...' : 'Выберите проект'}
            </option>
            {projects.map(project => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
          <div className="pointer-events-none absolute inset-y-0 right-2 flex items-center text-slate-400">
            {loading || savingProject ? <Loader2 size={14} className="animate-spin" /> : <ChevronDown size={14} />}
          </div>
        </div>
      </div>
      {error && <p className="mt-1 text-[10px] font-semibold text-rose-600 truncate">{error}</p>}
    </div>
  );
};
