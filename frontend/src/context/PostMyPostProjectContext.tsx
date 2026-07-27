import React, { createContext, ReactNode, useContext, useEffect, useMemo, useState } from 'react';
import { apiClient } from '../api/client';
import { PostMyPostProject, PostMyPostProjectsResponse } from '../types';
import { useTelegram } from './TelegramContext';

type ProjectContextType = {
  projects: PostMyPostProject[];
  selectedProjectId: number | null;
  selectedProject: PostMyPostProject | null;
  loading: boolean;
  savingProject: boolean;
  error: string;
  refreshProjects: () => Promise<number | null>;
  selectProject: (projectId: number) => Promise<number | null>;
};

const PostMyPostProjectContext = createContext<ProjectContextType | undefined>(undefined);

const resolveSelectedProjectId = (data: PostMyPostProjectsResponse) => (
  data.selected_project_id ?? data.projects.find(project => project.selected)?.id ?? data.projects[0]?.id ?? null
);

export const PostMyPostProjectProvider = ({ children }: { children: ReactNode }) => {
  const { telegramId } = useTelegram();
  const [projects, setProjects] = useState<PostMyPostProject[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [savingProject, setSavingProject] = useState(false);
  const [error, setError] = useState('');

  const applyProjectsData = (data: PostMyPostProjectsResponse) => {
    const nextProjectId = resolveSelectedProjectId(data);
    setProjects(data.projects);
    setSelectedProjectId(nextProjectId);
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
    setSavingProject(true);
    setSelectedProjectId(projectId);
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
        loading,
        savingProject,
        error,
        refreshProjects,
        selectProject,
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
