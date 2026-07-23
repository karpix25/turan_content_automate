import React, { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { Globe2, Loader2 } from 'lucide-react';
import { apiClient } from '../../api/client';
import { getApiErrorMessage } from '../../api/errors';
import { useTelegram } from '../../context/TelegramContext';
import { EndingClip, PostMyPostProject, PostMyPostProjectsResponse, PublishAccount, UniqueizationMode } from '../../types';
import { ChannelAccountCard } from './channels/ChannelAccountCard';
import { PostMyPostProjectSelector } from './channels/PostMyPostProjectSelector';

export const ChannelsTab: React.FC = () => {
  const { telegramId } = useTelegram();
  const [projects, setProjects] = useState<PostMyPostProject[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [selectedUniqueizationMode, setSelectedUniqueizationMode] = useState<UniqueizationMode>('auto');
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [savingProject, setSavingProject] = useState(false);
  const [savingUniqueizationMode, setSavingUniqueizationMode] = useState(false);
  const [publishAccounts, setPublishAccounts] = useState<PublishAccount[]>([]);
  const [channelDescriptions, setChannelDescriptions] = useState<Record<number, string>>({});
  const [publishLimitByAccount, setPublishLimitByAccount] = useState<Record<number, number>>({});
  const [selectedPlateIdsByAccount, setSelectedPlateIdsByAccount] = useState<Record<number, number[]>>({});
  const [plateStartPercentByAccount, setPlateStartPercentByAccount] = useState<Record<number, number>>({});
  const [collapsedAccounts, setCollapsedAccounts] = useState<Record<number, boolean>>({});
  const [channelsLoading, setChannelsLoading] = useState(false);
  const [channelsError, setChannelsError] = useState('');
  const [savingChannelSettings, setSavingChannelSettings] = useState(false);

  const [endingClips, setEndingClips] = useState<EndingClip[]>([]);
  const [deletingPlateId, setDeletingPlateId] = useState<number | null>(null);
  const [deletingEndingId, setDeletingEndingId] = useState<number | null>(null);

  const [plateUploadTarget, setPlateUploadTarget] = useState<PublishAccount | null>(null);
  const [uploadingPlateAccountId, setUploadingPlateAccountId] = useState<number | null>(null);
  const [endingUploadTarget, setEndingUploadTarget] = useState<PublishAccount | null>(null);
  const [uploadingEndingAccountId, setUploadingEndingAccountId] = useState<number | null>(null);
  const [saved, setSaved] = useState(false);

  const plateInputRef = useRef<HTMLInputElement>(null);
  const endingInputRef = useRef<HTMLInputElement>(null);
  const API_BASE = import.meta.env.VITE_API_BASE || '/api';

  const getMediaUrl = (path: string) => {
    if (!path) return '';
    const parts = path.split('/media/');
    if (parts.length > 1) return `${API_BASE}/media/${parts[1]}`;
    return '';
  };

  const flashSaved = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const normalizeUniqueizationMode = (mode?: UniqueizationMode | null): UniqueizationMode => (
    mode === 'light' || mode === 'standard' || mode === 'aggressive' || mode === 'off' ? mode : 'auto'
  );

  const applyProjectsData = (data: PostMyPostProjectsResponse) => {
    const nextProjectId = data.selected_project_id ?? data.projects.find(project => project.selected)?.id ?? data.projects[0]?.id ?? null;
    const selectedProject = data.projects.find(project => project.id === nextProjectId);
    setProjects(data.projects);
    setSelectedProjectId(nextProjectId);
    setSelectedUniqueizationMode(
      normalizeUniqueizationMode(data.selected_project_uniqueization_mode ?? selectedProject?.uniqueization_mode),
    );
    return nextProjectId;
  };

  const applyChannelsData = (data: PublishAccount[]) => {
    setPublishAccounts(data);
    const descMap: Record<number, string> = {};
    const limitMap: Record<number, number> = {};
    const platesMap: Record<number, number[]> = {};
    const percentsMap: Record<number, number> = {};
    data.forEach(acc => {
      descMap[acc.account_id] = acc.description || '';
      limitMap[acc.account_id] = acc.publish_limit_per_day || 3;
      platesMap[acc.account_id] = acc.selected_plate_ids || [];
      percentsMap[acc.account_id] = acc.plate_start_percent ?? 50;
    });
    setChannelDescriptions(descMap);
    setPublishLimitByAccount(limitMap);
    setSelectedPlateIdsByAccount(platesMap);
    setPlateStartPercentByAccount(percentsMap);
    setCollapsedAccounts(prev => {
      const next = { ...prev };
      data.forEach(acc => {
        if (next[acc.account_id] === undefined) next[acc.account_id] = true;
      });
      return next;
    });
  };

  const loadProjects = async () => {
    if (!telegramId) return null;
    setProjectsLoading(true);
    try {
      const data = await apiClient.getPostMyPostProjects(telegramId);
      return applyProjectsData(data);
    } catch (error: any) {
      setChannelsError(error.response?.data?.detail || error.message || 'Ошибка загрузки проектов PostMyPost');
      return null;
    } finally {
      setProjectsLoading(false);
    }
  };

  const loadChannels = async (projectId = selectedProjectId) => {
    if (!telegramId || !projectId) return;
    setChannelsLoading(true);
    setChannelsError('');
    try {
      const data = await apiClient.getChannels(telegramId, projectId);
      applyChannelsData(data);
    } catch (error: any) {
      setChannelsError(error.response?.data?.detail || error.message || 'Ошибка загрузки каналов');
    } finally {
      setChannelsLoading(false);
    }
  };

  const loadEndings = async (projectId = selectedProjectId) => {
    if (!telegramId || !projectId) return;
    try {
      const data = await apiClient.getEndings(telegramId, projectId);
      setEndingClips(data);
    } catch (error) {
    }
  };

  useEffect(() => {
    if (!telegramId) return;
    loadProjects().then(projectId => {
      if (!projectId) return;
      loadChannels(projectId);
      loadEndings(projectId);
    });
  }, [telegramId]);

  const buildChannelSettingsPayload = (
    plateIdsByAccount = selectedPlateIdsByAccount,
    accounts = publishAccounts,
  ) => ({
    account_ids: accounts.filter(a => a.enabled).map(a => a.account_id),
    descriptions: channelDescriptions,
    publish_limits_per_day: publishLimitByAccount,
    selected_plate_ids: plateIdsByAccount,
    plate_start_percents: plateStartPercentByAccount,
  });

  const saveChannelSettings = async () => {
    if (!telegramId || !selectedProjectId) return;
    setSavingChannelSettings(true);
    try {
      const data = await apiClient.updateChannels(telegramId, selectedProjectId, buildChannelSettingsPayload());
      applyChannelsData(data);
      flashSaved();
    } catch (error: any) {
      alert(error.response?.data?.detail || error.message || 'Ошибка сохранения каналов');
    } finally {
      setSavingChannelSettings(false);
    }
  };

  const handleProjectChange = async (projectId: number) => {
    if (!telegramId || projectId === selectedProjectId || savingProject) return;
    const nextProject = projects.find(project => project.id === projectId);
    setSavingProject(true);
    setSelectedProjectId(projectId);
    setSelectedUniqueizationMode(normalizeUniqueizationMode(nextProject?.uniqueization_mode));
    try {
      const data = await apiClient.updatePostMyPostProject(telegramId, projectId);
      applyProjectsData(data);
      await loadChannels(projectId);
      await loadEndings(projectId);
      flashSaved();
    } catch (error: any) {
      alert(error.response?.data?.detail || error.message || 'Ошибка выбора контейнера PostMyPost');
      await loadProjects();
    } finally {
      setSavingProject(false);
    }
  };

  const handleUniqueizationModeChange = async (mode: UniqueizationMode) => {
    if (!telegramId || !selectedProjectId || savingUniqueizationMode) return;
    const previousMode = selectedUniqueizationMode;
    setSelectedUniqueizationMode(mode);
    setSavingUniqueizationMode(true);
    try {
      const data = await apiClient.updatePostMyPostProject(telegramId, selectedProjectId, mode);
      applyProjectsData(data);
      flashSaved();
    } catch (error: any) {
      setSelectedUniqueizationMode(previousMode);
      alert(error.response?.data?.detail || error.message || 'Ошибка сохранения режима уникализации');
    } finally {
      setSavingUniqueizationMode(false);
    }
  };

  const handleAccountToggle = async (accountId: number) => {
    if (!telegramId || !selectedProjectId || savingChannelSettings) return;
    const previousAccounts = publishAccounts;
    const nextAccounts = publishAccounts.map(acc =>
      acc.account_id === accountId ? { ...acc, enabled: !acc.enabled } : acc
    );
    setPublishAccounts(nextAccounts);
    setSavingChannelSettings(true);
    try {
      const data = await apiClient.updateChannels(
        telegramId,
        selectedProjectId,
        buildChannelSettingsPayload(selectedPlateIdsByAccount, nextAccounts),
      );
      applyChannelsData(data);
      flashSaved();
    } catch (error: any) {
      setPublishAccounts(previousAccounts);
      alert(error.response?.data?.detail || error.message || 'Ошибка автосохранения канала');
    } finally {
      setSavingChannelSettings(false);
    }
  };

  const toggleAccountCollapse = (accountId: number) => {
    setCollapsedAccounts(prev => ({
      ...prev,
      [accountId]: !prev[accountId],
    }));
  };

  const deletePlate = async (plateId: number) => {
    if (!telegramId || !selectedProjectId) return;
    if (!window.confirm('Точно удалить плашку?')) return;
    setDeletingPlateId(plateId);
    try {
      const account = publishAccounts.find(acc => (acc.plate_assets || []).some(plate => plate.id === plateId));
      await apiClient.deletePlate(telegramId, plateId, selectedProjectId, account?.account_id);
      await loadChannels(selectedProjectId);
    } catch (error) {
    } finally {
      setDeletingPlateId(null);
    }
  };

  const deleteEnding = async (endingId: number) => {
    if (!telegramId || !selectedProjectId) return;
    if (!window.confirm('Точно удалить концовку?')) return;
    setDeletingEndingId(endingId);
    try {
      const ending = endingClips.find(item => item.id === endingId);
      await apiClient.deleteEnding(telegramId, endingId, selectedProjectId, ending?.account_id);
      await loadEndings(selectedProjectId);
    } catch (error) {
    } finally {
      setDeletingEndingId(null);
    }
  };

  const handlePlateUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !telegramId || !selectedProjectId || !plateUploadTarget) return;
    setUploadingPlateAccountId(plateUploadTarget.account_id);
    try {
      const newPlate = await apiClient.uploadPlate(telegramId, file, selectedProjectId, plateUploadTarget.account_id);
      const nextPlateIdsByAccount = {
        ...selectedPlateIdsByAccount,
        [plateUploadTarget.account_id]: [
          ...(selectedPlateIdsByAccount[plateUploadTarget.account_id] || []),
          newPlate.id,
        ],
      };

      setSelectedPlateIdsByAccount(nextPlateIdsByAccount);
      await apiClient.updateChannels(telegramId, selectedProjectId, buildChannelSettingsPayload(nextPlateIdsByAccount));
      flashSaved();
      await loadChannels(selectedProjectId);
    } catch (error) {
      alert(getApiErrorMessage(error, 'Ошибка при загрузке плашки'));
    } finally {
      setUploadingPlateAccountId(null);
      setPlateUploadTarget(null);
      if (plateInputRef.current) plateInputRef.current.value = '';
    }
  };

  const handleEndingUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !telegramId || !selectedProjectId || !endingUploadTarget) return;
    setUploadingEndingAccountId(endingUploadTarget.account_id);
    try {
      await apiClient.uploadEnding(telegramId, file, {
        projectId: selectedProjectId,
        accountId: endingUploadTarget.account_id,
        platform: 'universal',
      });
      await loadEndings(selectedProjectId);
    } catch (error) {
      alert(getApiErrorMessage(error, 'Ошибка при загрузке концовки'));
    } finally {
      setUploadingEndingAccountId(null);
      setEndingUploadTarget(null);
      if (endingInputRef.current) endingInputRef.current.value = '';
    }
  };

  const clampPercent = (value: number) => Math.max(0, Math.min(100, Math.round(value)));
  const clampPublishLimit = (value: number) => Math.max(2, Math.min(96, Math.round(value)));

  return (
    <motion.div key="channels" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-4 pb-20">
      <div className="sticky top-[61px] z-30 -mx-4 px-4 py-2 bg-[#f1f2f6]/95 backdrop-blur flex items-center justify-between gap-2">
        <button
          onClick={() => {
            loadProjects().then(projectId => {
              const nextProjectId = projectId || selectedProjectId;
              if (!nextProjectId) return;
              loadChannels(nextProjectId);
              loadEndings(nextProjectId);
            });
          }}
          disabled={channelsLoading || projectsLoading}
          className="h-10 px-3 bg-white border border-slate-200 text-slate-700 text-xs sm:text-sm font-bold rounded-xl flex items-center justify-center gap-2 shadow-sm disabled:opacity-50"
        >
          {(channelsLoading || projectsLoading) ? <Loader2 className="animate-spin" size={16} /> : <Globe2 size={16} />}
          Обновить список
        </button>
        <button
          onClick={saveChannelSettings}
          disabled={savingChannelSettings || savingProject || savingUniqueizationMode}
          className={`h-10 px-3 sm:px-5 text-xs sm:text-sm font-bold rounded-xl flex items-center justify-center gap-2 shadow-lg transition-all ${
            saved ? 'bg-[#34c759] text-white shadow-green-500/20' : 'bg-[#24a1de] text-white shadow-blue-500/20'
          } disabled:opacity-50`}
        >
          {(savingChannelSettings || savingProject || savingUniqueizationMode) ? <Loader2 className="animate-spin" size={16} /> : null}
          {saved ? 'Сохранено!' : 'Сохранить настройки'}
        </button>
      </div>

      <PostMyPostProjectSelector
        projects={projects}
        selectedProjectId={selectedProjectId}
        loading={projectsLoading}
        disabled={savingProject || channelsLoading || savingUniqueizationMode}
        accountsCount={publishAccounts.length}
        uniqueizationMode={selectedUniqueizationMode}
        onUniqueizationModeChange={handleUniqueizationModeChange}
        onChange={handleProjectChange}
      />

      {channelsError && (
        <div className="p-4 rounded-2xl bg-rose-50 border border-rose-100 text-rose-600 text-sm font-medium">
          {channelsError}
        </div>
      )}

      {channelsLoading && publishAccounts.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 gap-3 text-slate-400">
          <Loader2 className="animate-spin w-8 h-8" />
          <p className="text-sm font-medium">Загрузка аккаунтов...</p>
        </div>
      ) : publishAccounts.length === 0 && !channelsError ? (
        <div className="flex flex-col items-center justify-center py-10 px-4 text-center bg-white rounded-2xl border border-slate-100 shadow-sm">
          <Globe2 className="w-12 h-12 text-slate-200 mb-3" />
          <h3 className="text-lg font-bold text-slate-800 mb-1">Нет аккаунтов</h3>
          <p className="text-sm text-slate-500">Подключите аккаунты внутри выбранного контейнера PostMyPost</p>
        </div>
      ) : (
        <div className="space-y-4">
          <input
            type="file"
            accept="image/*,video/webm,video/quicktime,.webm,.mov"
            className="hidden"
            ref={plateInputRef}
            onChange={handlePlateUpload}
          />
          <input
            type="file"
            accept="video/mp4,video/quicktime"
            className="hidden"
            ref={endingInputRef}
            onChange={handleEndingUpload}
          />

          {publishAccounts.map(account => (
            <ChannelAccountCard
              key={account.account_id}
              account={account}
              accountEndings={endingClips.filter(e => e.account_id === account.account_id)}
              isCollapsed={Boolean(collapsedAccounts[account.account_id])}
              isSaving={savingChannelSettings}
              isUploadingPlate={uploadingPlateAccountId === account.account_id}
              isUploadingEnding={uploadingEndingAccountId === account.account_id}
              deletingPlateId={deletingPlateId}
              deletingEndingId={deletingEndingId}
              description={channelDescriptions[account.account_id] || ''}
              publishLimit={publishLimitByAccount[account.account_id] ?? 3}
              plateStartPercent={plateStartPercentByAccount[account.account_id] ?? 50}
              getMediaUrl={getMediaUrl}
              onToggleEnabled={handleAccountToggle}
              onToggleCollapse={toggleAccountCollapse}
              onDescriptionChange={(accountId, value) => setChannelDescriptions(prev => ({ ...prev, [accountId]: value }))}
              onPublishLimitChange={(accountId, value) => setPublishLimitByAccount(prev => ({ ...prev, [accountId]: clampPublishLimit(value) }))}
              onPlateStartPercentChange={(accountId, value) => setPlateStartPercentByAccount(prev => ({ ...prev, [accountId]: clampPercent(value) }))}
              onUploadPlate={(targetAccount) => { setPlateUploadTarget(targetAccount); plateInputRef.current?.click(); }}
              onUploadEnding={(targetAccount) => { setEndingUploadTarget(targetAccount); endingInputRef.current?.click(); }}
              onDeletePlate={deletePlate}
              onDeleteEnding={deleteEnding}
            />
          ))}
        </div>
      )}
    </motion.div>
  );
};
