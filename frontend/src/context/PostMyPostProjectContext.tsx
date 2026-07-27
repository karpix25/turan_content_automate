import React, { createContext, ReactNode, useContext, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../api/client';
import { PostMyPostProject, PostMyPostProjectsResponse, UniqueizationMode } from '../types';
import { useTelegram } from './TelegramContext';

type ProjectContextType = {
  projects: PostMyPostProject[];
  selectedProjectId: number | null;
  selectedProject: PostMyPostProject | null;
  selectedUniqueizationMode: UniqueizationMode;
  loading: boolean;
  savingProject: boolean;
  savingUniqueizationMode: boolean;
  error: string;
  refreshProjects: () => Promise<number | null>;
  selectProject: (projectId: number) => Promise<number | null>;
  setUniqueizationMode: (mode: UniqueizationMode) => Promise<void>;
};

const PostMyPostProjectContext = createContext<ProjectContextType | undefined>(undefined);

const normalizeUniqueizationMode = (mode?: UniqueizationMode | null): UniqueizationMode => (
  mode === 'light' || mode === 'standard' || mode === 'aggressive' || mode === 'off' ? mode : 'auto'
);

const resolveSelectedProjectId = (data: PostMyPostProjectsResponse) => (
  data.selected_project_id ?? data.projects.find(project => project.selected)?.id ?? data.projects[0]?.id ?? null
);

export const PostMyPostProjectProvider = ({ children }: { children: ReactNode }) => {
  const { telegramId } = useTelegram();
  const [projects, setProjects] = useState<PostMyPostProject[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [selectedUniqueizationMode, setSelectedUniqueizationMode] = useState<UniqueizationMode>('auto');
  const [loading, setLoading] = useState(false);
  const [savingProject, setSavingProject] = useState(false);
  const [savingUniqueizationMode, setSavingUniqueizationMode] = useState(false);
  const [error, setError] = useState('');

  const applyProjectsData = (data: PostMyPostProjectsResponse) => {
    const nextProjectId = resolveSelectedProjectId(data);
    const selectedProject = data.projects.find(project => project.id === nextProjectId);
    setProjects(data.projects);
    setSelectedProjectId(nextProjectId);
    setSelectedUniqueizationMode(
      normalizeUniqueizationMode(data.selected_project_uniqueization_mode ?? selectedProject?.uniqueization_mode),
    );
    setError('');
    return nextProjectId;
  };

  const refreshProjects = async () => {
    if (!telegramId) {
      setProjects([]);
      setSelectedProjectId(null);
      return null;
    }
    setLoading(true);
    try {
      const data = await apiClient.getPostMyPostProjects(telegramId);
      return applyProjectsData(data);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Ошибка загрузки проектов PostMyPost');
      return null;
    } finally {
      setLoading(false);
    }
  };

  const selectProject = async (projectId: number) => {
    if (!telegramId || projectId === selectedProjectId || savingProject) return selectedProjectId;
    const nextProject = projects.find(project => project.id === projectId);
    setSavingProject(true);
    setSelectedProjectId(projectId);
    setSelectedUniqueizationMode(normalizeUniqueizationMode(nextProject?.uniqueization_mode));
    try {
      const data = await apiClient.updatePostMyPostProject(telegramId, projectId);
      return applyProjectsData(data);
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || 'Ошибка выбора проекта PostMyPost');
      await refreshProjects();
      return selectedProjectId;
    } finally {
      setSavingProject(false);
    }
  };

  const setUniqueizationMode = async (mode: UniqueizationMode) => {
    if (!telegramId || !selectedProjectId || savingUniqueizationMode) return;
    const previousMode = selectedUniqueizationMode;
    setSelectedUniqueizationMode(mode);
    setSavingUniqueizationMode(true);
    try {
      const data = await apiClient.updatePostMyPostProject(telegramId, selectedProjectId, mode);
      applyProjectsData(data);
    } catch (err: any) {
      setSelectedUniqueizationMode(previousMode);
      setError(err.response?.data?.detail || err.message || 'Ошибка сохранения режима уникализации');
    } finally {
      setSavingUniqueizationMode(false);
    }
  };

  useEffect(() => {
    refreshProjects();
  }, [telegramId]);

  const selectedProject = useMemo(
    () => projects.find(project => project.id === selectedProjectId) || null,
    [projects, selectedProjectId],
  );

  return (
    <PostMyPostProjectContext.Provider
      value={{
        projects,
        selectedProjectId,
        selectedProject,
        selectedUniqueizationMode,
        loading,
        savingProject,
        savingUniqueizationMode,
        error,
        refreshProjects,
        selectProject,
        setUniqueizationMode,
      }}
    >
      {children}
    </PostMyPostProjectContext.Provider>
  );
};

export const usePostMyPostProject = () => {
  const context = useContext(PostMyPostProjectContext);
  if (context === undefined) {
    throw new Error('usePostMyPostProject must be used within a PostMyPostProjectProvider');
  }
  return context;
};
