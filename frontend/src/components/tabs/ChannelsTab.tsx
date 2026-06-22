import React, { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { ChevronDown, Film, Globe2, Upload, Loader2, Trash2 } from 'lucide-react';
import { apiClient } from '../../api/client';
import { getApiErrorMessage } from '../../api/errors';
import { useTelegram } from '../../context/TelegramContext';
import { PublishAccount, EndingClip } from '../../types';

export const ChannelsTab: React.FC = () => {
  const { telegramId } = useTelegram();
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

  const loadChannels = async () => {
    if (!telegramId) return;
    setChannelsLoading(true);
    try {
      const data = await apiClient.getChannels(telegramId);
      applyChannelsData(data);
    } catch (error: any) {
      setChannelsError(error.response?.data?.detail || error.message || 'Ошибка загрузки каналов');
    } finally {
      setChannelsLoading(false);
    }
  };

  const loadEndings = async () => {
    if (!telegramId) return;
    try {
      const data = await apiClient.getEndings(telegramId);
      setEndingClips(data);
    } catch (error) {
    }
  };

  useEffect(() => {
    loadChannels();
    loadEndings();
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
    if (!telegramId) return;
    setSavingChannelSettings(true);
    try {
      const data = await apiClient.updateChannels(telegramId, buildChannelSettingsPayload());
      applyChannelsData(data);
      flashSaved();
    } catch (error: any) {
      alert(error.response?.data?.detail || error.message || 'Ошибка сохранения каналов');
    } finally {
      setSavingChannelSettings(false);
    }
  };

  const handleAccountToggle = async (accountId: number) => {
    if (!telegramId || savingChannelSettings) return;
    const previousAccounts = publishAccounts;
    const nextAccounts = publishAccounts.map(acc =>
      acc.account_id === accountId ? { ...acc, enabled: !acc.enabled } : acc
    );
    setPublishAccounts(nextAccounts);
    setSavingChannelSettings(true);
    try {
      const data = await apiClient.updateChannels(
        telegramId,
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
    if (!telegramId) return;
    if (!window.confirm('Точно удалить плашку?')) return;
    setDeletingPlateId(plateId);
    try {
      await apiClient.deletePlate(telegramId, plateId);
      await loadChannels();
    } catch (error) {
    } finally {
      setDeletingPlateId(null);
    }
  };

  const deleteEnding = async (endingId: number) => {
    if (!telegramId) return;
    if (!window.confirm('Точно удалить концовку?')) return;
    setDeletingEndingId(endingId);
    try {
      await apiClient.deleteEnding(telegramId, endingId);
      await loadEndings();
    } catch (error) {
    } finally {
      setDeletingEndingId(null);
    }
  };

  const handlePlateUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !telegramId || !plateUploadTarget) return;
    setUploadingPlateAccountId(plateUploadTarget.account_id);
    try {
      const newPlate = await apiClient.uploadPlate(telegramId, file, plateUploadTarget.account_id);
      const nextPlateIdsByAccount = {
        ...selectedPlateIdsByAccount,
        [plateUploadTarget.account_id]: [
          ...(selectedPlateIdsByAccount[plateUploadTarget.account_id] || []),
          newPlate.id,
        ],
      };
      
      setSelectedPlateIdsByAccount(nextPlateIdsByAccount);
      await apiClient.updateChannels(telegramId, buildChannelSettingsPayload(nextPlateIdsByAccount));
      flashSaved();
      await loadChannels();
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
    if (!file || !telegramId || !endingUploadTarget) return;
    setUploadingEndingAccountId(endingUploadTarget.account_id);
    try {
      await apiClient.uploadEnding(telegramId, file, {
        accountId: endingUploadTarget.account_id,
        platform: 'universal',
      });
      await loadEndings();
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
          onClick={loadChannels}
          disabled={channelsLoading}
          className="h-10 px-3 bg-white border border-slate-200 text-slate-700 text-xs sm:text-sm font-bold rounded-xl flex items-center justify-center gap-2 shadow-sm disabled:opacity-50"
        >
          {channelsLoading ? <Loader2 className="animate-spin" size={16} /> : <Globe2 size={16} />}
          Обновить список
        </button>
        <button
          onClick={saveChannelSettings}
          disabled={savingChannelSettings}
          className={`h-10 px-3 sm:px-5 text-xs sm:text-sm font-bold rounded-xl flex items-center justify-center gap-2 shadow-lg transition-all ${
            saved ? 'bg-[#34c759] text-white shadow-green-500/20' : 'bg-[#24a1de] text-white shadow-blue-500/20'
          } disabled:opacity-50`}
        >
          {savingChannelSettings ? <Loader2 className="animate-spin" size={16} /> : null}
          {saved ? 'Сохранено!' : 'Сохранить настройки'}
        </button>
      </div>

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
          <p className="text-sm text-slate-500">Добавьте аккаунты в PostMyPost</p>
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

          {publishAccounts.map(account => {
            const isUploadingPlate = uploadingPlateAccountId === account.account_id;
            const isUploadingEnding = uploadingEndingAccountId === account.account_id;
            const accountEndings = endingClips.filter(e => e.account_id === account.account_id);
            const isCollapsed = Boolean(collapsedAccounts[account.account_id]);
            return (
              <div key={account.account_id} className={`tg-card overflow-hidden transition-opacity ${!account.enabled ? 'opacity-60' : ''}`}>
                <div className="p-4">
                  <div className="flex items-start justify-between gap-4 mb-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => toggleAccountCollapse(account.account_id)}
                          className="h-8 w-8 -ml-1 rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-900 flex items-center justify-center transition-colors"
                          aria-label={isCollapsed ? 'Развернуть канал' : 'Свернуть канал'}
                        >
                          <ChevronDown
                            size={18}
                            className={`transition-transform ${isCollapsed ? '-rotate-90' : 'rotate-0'}`}
                          />
                        </button>
                        <h4 className="text-[17px] font-bold text-slate-900 leading-tight truncate">
                          {account.account_name}
                        </h4>
                      </div>
                      <p className="text-xs text-slate-500 mt-1">
                        Канал: {account.channel_name || 'Неизвестно'} <span className="opacity-50">({account.channel_code})</span>
                      </p>
                    </div>
                    <button
                      onClick={() => handleAccountToggle(account.account_id)}
                      disabled={savingChannelSettings}
                      className={`relative inline-flex h-7 w-12 items-center rounded-full transition-colors shrink-0 ${account.enabled ? 'bg-[#34c759]' : 'bg-[#e9e9eb]'}`}
                    >
                      <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${account.enabled ? 'translate-x-6' : 'translate-x-1'}`} />
                    </button>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    <span className={`px-2 py-1 rounded-lg text-[10px] font-bold ${account.description ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                      Описание {account.description ? 'есть' : 'нет'}
                    </span>
                    <span className={`px-2 py-1 rounded-lg text-[10px] font-bold ${(account.plate_assets || []).length > 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                      Плашки {(account.plate_assets || []).length}
                    </span>
                    <span className={`px-2 py-1 rounded-lg text-[10px] font-bold ${accountEndings.length > 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                      Концовки {accountEndings.length}
                    </span>
                  </div>

                  {account.enabled && !isCollapsed && (
                    <div className="mt-4 space-y-4 pt-4 border-t border-slate-100">
                      <div>
                        <label className="text-xs font-bold text-[#707579] uppercase tracking-wider mb-2 block">Лимит публикаций в день</label>
                        <div className="flex items-center gap-3">
                          <input
                            type="range"
                            min="2"
                            max="20"
                            value={publishLimitByAccount[account.account_id] ?? 3}
                            onChange={(e) => setPublishLimitByAccount(prev => ({ ...prev, [account.account_id]: clampPublishLimit(Number(e.target.value)) }))}
                            className="flex-1 accent-[#24a1de]"
                          />
                          <input
                            type="number"
                            min="2"
                            max="96"
                            value={publishLimitByAccount[account.account_id] ?? 3}
                            onChange={(e) => setPublishLimitByAccount(prev => ({ ...prev, [account.account_id]: clampPublishLimit(Number(e.target.value)) }))}
                            className="input-field h-10 w-16 text-center text-sm font-bold"
                          />
                        </div>
                        <p className="text-[11px] text-slate-500 mt-2 leading-relaxed">
                          Vizard занимает до половины лимита, остальные слоты остаются для быстрых форматов.
                        </p>
                      </div>

                      <div>
                        <label className="text-xs font-bold text-[#707579] uppercase tracking-wider mb-2 block">Описание (шаблон поста)</label>
                        <textarea
                          value={channelDescriptions[account.account_id] || ''}
                          onChange={(e) => setChannelDescriptions(prev => ({ ...prev, [account.account_id]: e.target.value }))}
                          placeholder="Введите текст, который будет добавляться к каждому посту..."
                          className="input-field text-sm min-h-[80px] leading-relaxed resize-y"
                        />
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="bg-slate-50 rounded-xl p-3 border border-slate-100">
                          <div className="flex items-center justify-between mb-3">
                            <label className="text-xs font-bold text-[#707579] uppercase tracking-wider">Плашки</label>
                            <button
                              onClick={() => { setPlateUploadTarget(account); plateInputRef.current?.click(); }}
                              disabled={isUploadingPlate}
                              className="text-[#24a1de] hover:bg-blue-50 p-1.5 rounded-lg transition-colors disabled:opacity-50"
                            >
                              {isUploadingPlate ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
                            </button>
                          </div>
                          
                          <div className="space-y-2 mb-3">
                            {account.plate_assets?.map(plate => {
                              const isVideoPlate = plate.media_type === 'video';
                              return (
                                <div key={plate.id} className="flex items-center gap-2 bg-white p-1.5 rounded-lg border border-slate-100">
                                  {isVideoPlate ? (
                                    <video
                                      src={getMediaUrl(plate.file_path)}
                                      muted
                                      playsInline
                                      className="w-8 h-8 object-cover rounded bg-slate-100"
                                    />
                                  ) : (
                                    <img src={getMediaUrl(plate.file_path)} alt="Plate" className="w-8 h-8 object-cover rounded bg-slate-100" />
                                  )}
                                  <span className="text-[10px] text-slate-500 flex-1 truncate">{plate.file_path.split('/').pop()}</span>
                                  {isVideoPlate && (
                                    <span className="h-6 w-6 rounded-md bg-blue-50 text-[#24a1de] flex items-center justify-center" title="Видео-плашка">
                                      <Film size={13} />
                                    </span>
                                  )}
                                  <button
                                    onClick={() => deletePlate(plate.id)}
                                    disabled={deletingPlateId === plate.id}
                                    className="p-1.5 text-slate-400 hover:text-rose-500 rounded-md"
                                  >
                                    {deletingPlateId === plate.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                                  </button>
                                </div>
                              );
                            })}
                            {(!account.plate_assets || account.plate_assets.length === 0) && (
                              <p className="text-xs text-slate-400 italic">Нет загруженных плашек</p>
                            )}
                          </div>

                          <div className="flex items-center gap-2">
                            <span className="text-[10px] font-medium text-slate-500 whitespace-nowrap">Время (%):</span>
                            <input
                              type="number"
                              min="0" max="100"
                              value={plateStartPercentByAccount[account.account_id] ?? 50}
                              onChange={(e) => setPlateStartPercentByAccount(prev => ({ ...prev, [account.account_id]: clampPercent(Number(e.target.value)) }))}
                              className="input-field h-7 text-xs px-2"
                            />
                          </div>
                        </div>

                        <div className="bg-slate-50 rounded-xl p-3 border border-slate-100">
                          <div className="flex items-center justify-between mb-3">
                            <label className="text-xs font-bold text-[#707579] uppercase tracking-wider">Концовки</label>
                            <button
                              onClick={() => { setEndingUploadTarget(account); endingInputRef.current?.click(); }}
                              disabled={isUploadingEnding}
                              className="text-[#24a1de] hover:bg-blue-50 p-1.5 rounded-lg transition-colors disabled:opacity-50"
                            >
                              {isUploadingEnding ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
                            </button>
                          </div>

                          <div className="space-y-2">
                            {accountEndings.map(ending => (
                              <div key={ending.id} className="flex items-center gap-2 bg-white p-1.5 rounded-lg border border-slate-100">
                                <div className="w-8 h-8 rounded bg-slate-100 overflow-hidden flex-shrink-0">
                                  {ending.file_path.toLowerCase().endsWith('.mp4') ? (
                                    <video src={getMediaUrl(ending.file_path)} className="w-full h-full object-cover" />
                                  ) : (
                                    <img src={getMediaUrl(ending.file_path)} className="w-full h-full object-cover" />
                                  )}
                                </div>
                                <span className="text-[10px] font-bold bg-slate-100 px-1.5 py-0.5 rounded text-slate-500 uppercase">
                                  {ending.platform}
                                </span>
                                <span className="text-[10px] text-slate-500 flex-1 truncate">{ending.file_path.split('/').pop()}</span>
                                <button
                                  onClick={() => deleteEnding(ending.id)}
                                  disabled={deletingEndingId === ending.id}
                                  className="p-1.5 text-slate-400 hover:text-rose-500 rounded-md"
                                >
                                  {deletingEndingId === ending.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                                </button>
                              </div>
                            ))}
                            {accountEndings.length === 0 && (
                              <p className="text-xs text-slate-400 italic">Нет загруженных концовок</p>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </motion.div>
  );
};
