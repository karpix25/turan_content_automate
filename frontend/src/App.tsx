import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Image as ImageIcon, Video, Upload, CalendarClock, RefreshCcw, LayoutGrid, ChevronRight, X, Eye } from 'lucide-react';
import axios from 'axios';

type UserSettings = {
  auto_schedule_enabled: boolean;
  publish_limit_per_day: number;
  publish_window_start_msk: string;
  publish_window_end_msk: string;
  selected_plate_id?: number | null;
  plate_start_percent?: number;
};

type VideoTaskItem = {
  id: number;
  source_url: string;
  type: string;
  status: string;
  output_path?: string | null;
  publish_at?: string | null;
  publishing_status: string;
  created_at: string;
};

type PublishAccount = {
  account_id: number;
  account_name: string;
  account_login?: string | null;
  channel_id?: number | null;
  channel_code?: string | null;
  channel_name?: string | null;
  enabled: boolean;
  description?: string | null;
};

type EndingClip = {
  id: number;
  user_id: number;
  account_id?: number | null;
  file_path: string;
  label?: string | null;
  platform: string;
};

type TelegramWebApp = {
  initDataUnsafe?: {
    user?: {
      id?: number;
    };
  };
  ready?: () => void;
  expand?: () => void;
};

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp;
    };
  }
}

const API_BASE = import.meta.env.VITE_API_BASE || '/api';
const TELEGRAM_ID_STORAGE_KEY = 'content_studio_telegram_id';

const normalizeTelegramId = (value: unknown): string => {
  const text = String(value ?? '').trim();
  return /^\d{5,20}$/.test(text) ? text : '';
};

const clampPercent = (value: number) => Math.max(0, Math.min(100, Math.round(value)));

const App = () => {
  const [activeTab, setActiveTab] = useState('branding');
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showPreview, setShowPreview] = useState(false);

  const [autoScheduleEnabled, setAutoScheduleEnabled] = useState(false);
  const [publishLimitPerDay, setPublishLimitPerDay] = useState(3);
  const [publishWindowStartMsk, setPublishWindowStartMsk] = useState('10:00:00');
  const [publishWindowEndMsk, setPublishWindowEndMsk] = useState('22:00:00');
  const [plateFile, setPlateFile] = useState<File | null>(null);
  const [platePreviewUrl, setPlatePreviewUrl] = useState('');
  const [selectedPlateId, setSelectedPlateId] = useState<number | null>(null);
  const [plateStartPercent, setPlateStartPercent] = useState(0);
  const [uploadingPlate, setUploadingPlate] = useState(false);
  const [telegramId, setTelegramId] = useState('');
  const [telegramIdInput, setTelegramIdInput] = useState('');
  const [tasks, setTasks] = useState<VideoTaskItem[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [scheduleInputs, setScheduleInputs] = useState<Record<number, string>>({});
  const [activeTaskId, setActiveTaskId] = useState<number | null>(null);
  const [publishAccounts, setPublishAccounts] = useState<PublishAccount[]>([]);
  const [channelDescriptions, setChannelDescriptions] = useState<Record<number, string>>({});
  const [channelsLoading, setChannelsLoading] = useState(false);
  const [channelsError, setChannelsError] = useState('');
  const [savingChannelSettings, setSavingChannelSettings] = useState(false);
  const [endingClips, setEndingClips] = useState<EndingClip[]>([]);
  const [uploadingEndingAccountId, setUploadingEndingAccountId] = useState<number | null>(null);
  const [endingUploadTarget, setEndingUploadTarget] = useState<PublishAccount | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const endingInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const webApp = window.Telegram?.WebApp;
    if (webApp?.ready) webApp.ready();
    if (webApp?.expand) webApp.expand();

    const tgUserId = normalizeTelegramId(webApp?.initDataUnsafe?.user?.id);
    const query = new URLSearchParams(window.location.search);
    const queryId = normalizeTelegramId(query.get('telegram_id') || query.get('tg_id'));
    const storedId = normalizeTelegramId(window.localStorage.getItem(TELEGRAM_ID_STORAGE_KEY));
    const resolvedId = tgUserId || queryId || storedId;
    if (resolvedId) {
      setTelegramId(resolvedId);
      setTelegramIdInput(resolvedId);
      window.localStorage.setItem(TELEGRAM_ID_STORAGE_KEY, resolvedId);
    }
  }, []);

  const applyTelegramId = () => {
    const nextId = normalizeTelegramId(telegramIdInput);
    if (!nextId) {
      setChannelsError('Укажите корректный Telegram ID (только цифры).');
      return;
    }
    setChannelsError('');
    setTelegramId(nextId);
    setTelegramIdInput(nextId);
    window.localStorage.setItem(TELEGRAM_ID_STORAGE_KEY, nextId);
  };

  useEffect(() => {
    if (!telegramId) return;
    const loadSettings = async () => {
      try {
        const response = await axios.get<UserSettings>(`${API_BASE}/settings/${telegramId}`);
        setAutoScheduleEnabled(response.data.auto_schedule_enabled === true);
        setPublishLimitPerDay(response.data.publish_limit_per_day || 3);
        setPublishWindowStartMsk(response.data.publish_window_start_msk || '10:00:00');
        setPublishWindowEndMsk(response.data.publish_window_end_msk || '22:00:00');
        setSelectedPlateId(response.data.selected_plate_id ?? null);
        setPlateStartPercent(clampPercent(response.data.plate_start_percent ?? 0));
      } catch (error) {}
    };
    loadSettings();
  }, [telegramId]);

  const toLocalInput = (isoValue?: string | null): string => {
    if (!isoValue) return '';
    const date = new Date(isoValue);
    if (Number.isNaN(date.getTime())) return '';
    const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
    return localDate.toISOString().slice(0, 16);
  };

  const loadTasks = async (targetTelegramId: string) => {
    setTasksLoading(true);
    try {
      const response = await axios.get<VideoTaskItem[]>(`${API_BASE}/tasks/${targetTelegramId}`);
      setTasks(response.data);
      setScheduleInputs(
        response.data.reduce<Record<number, string>>((acc, task) => {
          acc[task.id] = toLocalInput(task.publish_at);
          return acc;
        }, {})
      );
    } catch (error) {
    } finally {
      setTasksLoading(false);
    }
  };

  const loadPublishAccounts = async (targetTelegramId: string) => {
    setChannelsLoading(true);
    try {
      const response = await axios.get<PublishAccount[]>(`${API_BASE}/postmypost/channels/${targetTelegramId}`);
      setPublishAccounts(response.data);
      setChannelDescriptions(
        response.data.reduce<Record<number, string>>((acc, item) => {
          acc[item.account_id] = item.description || '';
          return acc;
        }, {}),
      );
      setChannelsError('');
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      setChannelsError(detail ? String(detail) : 'Не удалось загрузить каналы из PostMyPost');
    } finally {
      setChannelsLoading(false);
    }
  };

  const loadEndingClips = async (targetTelegramId: string) => {
    try {
      const response = await axios.get<EndingClip[]>(`${API_BASE}/endings/${targetTelegramId}`);
      setEndingClips(response.data);
    } catch (error) {}
  };

  const normalizeNetwork = (code?: string | null) => {
    const normalized = (code || '').trim().toLowerCase();
    if (normalized.includes('instagram') || normalized === 'ig' || normalized === 'insta') return 'instagram';
    if (normalized.includes('youtube') || normalized === 'yt') return 'youtube';
    if (normalized.includes('tiktok') || normalized === 'tt') return 'tiktok';
    if (normalized === 'instagram' || normalized === 'youtube' || normalized === 'tiktok') return normalized;
    return normalized || 'other';
  };

  const getEndingForAccount = (accountId: number, platform?: string | null) => {
    const exact = endingClips.find((item) => item.account_id === accountId);
    if (exact) return exact;
    const normalizedPlatform = normalizeNetwork(platform);
    return endingClips.find((item) => !item.account_id && normalizeNetwork(item.platform) === normalizedPlatform) || null;
  };

  const buildDescriptionsPayload = (source: Record<number, string>) => {
    return Object.entries(source).reduce<Record<string, string>>((acc, [accountId, value]) => {
      const text = (value || '').trim();
      if (!text) return acc;
      acc[accountId] = text;
      return acc;
    }, {});
  };

  const savePublishChannelSettings = async (
    accounts: PublishAccount[],
    descriptions: Record<number, string>,
  ) => {
    if (!telegramId) return;
    const accountIds = accounts.filter((item) => item.enabled).map((item) => item.account_id);
    const payload = {
      account_ids: accountIds,
      descriptions: buildDescriptionsPayload(descriptions),
    };
    const response = await axios.post<PublishAccount[]>(`${API_BASE}/postmypost/channels/${telegramId}`, payload);
    setPublishAccounts(response.data);
    setChannelDescriptions(
      response.data.reduce<Record<number, string>>((acc, item) => {
        acc[item.account_id] = item.description || '';
        return acc;
      }, {}),
    );
  };

  const togglePublishAccount = async (accountId: number) => {
    if (!telegramId) return;
    const nextAccounts = publishAccounts.map((item) =>
      item.account_id === accountId ? { ...item, enabled: !item.enabled } : item,
    );
    setPublishAccounts(nextAccounts);
    try {
      await savePublishChannelSettings(nextAccounts, channelDescriptions);
    } catch (error) {}
  };

  const saveDescriptions = async () => {
    if (!telegramId) return;
    setSavingChannelSettings(true);
    try {
      await savePublishChannelSettings(publishAccounts, channelDescriptions);
    } catch (error) {
    } finally {
      setSavingChannelSettings(false);
    }
  };

  useEffect(() => {
    if (!telegramId) return;
    void loadTasks(telegramId);
    void loadPublishAccounts(telegramId);
    void loadEndingClips(telegramId);
  }, [telegramId]);

  const handlePickFile = () => fileInputRef.current?.click();

  const handlePlateSelected = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !telegramId) return;
    if (platePreviewUrl) URL.revokeObjectURL(platePreviewUrl);
    setPlatePreviewUrl(URL.createObjectURL(file));
    setPlateFile(file);
    const formData = new FormData();
    formData.append('file', file);
    setUploadingPlate(true);
    try {
      const response = await axios.post<{ plate_id: number }>(`${API_BASE}/upload/plate/${telegramId}`, formData);
      setSelectedPlateId(response.data.plate_id);
    } catch (error) {} finally {
      setUploadingPlate(false);
      event.target.value = '';
    }
  };

  const handlePickEnding = (account: PublishAccount) => {
    setEndingUploadTarget(account);
    endingInputRef.current?.click();
  };

  const handleEndingSelected = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !telegramId || !endingUploadTarget) return;
    const platform = normalizeNetwork(endingUploadTarget.channel_code);
    if (!['instagram', 'youtube', 'tiktok'].includes(platform)) return;
    const formData = new FormData();
    formData.append('file', file);
    formData.append('platform', platform);
    formData.append('label', file.name);
    formData.append('account_id', String(endingUploadTarget.account_id));
    setUploadingEndingAccountId(endingUploadTarget.account_id);
    try {
      await axios.post(`${API_BASE}/upload/ending/${telegramId}`, formData);
      await loadEndingClips(telegramId);
    } catch (error) {
    } finally {
      setUploadingEndingAccountId(null);
      setEndingUploadTarget(null);
      event.target.value = '';
    }
  };

  const flashSaved = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const saveBrandingSettings = async () => {
    if (!telegramId) return;
    setLoading(true);
    try {
      await axios.post(`${API_BASE}/settings/${telegramId}/update`, {
        subtitles_enabled: false,
        selected_plate_id: selectedPlateId,
        plate_start_percent: plateStartPercent,
      });
      flashSaved();
    } catch (error) {} finally {
      setLoading(false);
    }
  };

  const savePlanningSettings = async () => {
    if (!telegramId) return;
    setLoading(true);
    try {
      await axios.post(`${API_BASE}/settings/${telegramId}/update`, {
        subtitles_enabled: false,
        auto_schedule_enabled: autoScheduleEnabled,
        publish_limit_per_day: publishLimitPerDay,
        publish_window_start_msk: publishWindowStartMsk,
        publish_window_end_msk: publishWindowEndMsk,
      });
      flashSaved();
    } catch (error) {} finally {
      setLoading(false);
    }
  };

  const saveTaskSchedule = async (taskId: number) => {
    if (!telegramId) return;
    const localValue = scheduleInputs[taskId];
    if (!localValue) return;
    const publishAt = new Date(localValue);
    setActiveTaskId(taskId);
    try {
      await axios.patch(`${API_BASE}/tasks/${telegramId}/${taskId}/schedule`, { publish_at: publishAt.toISOString() });
      await loadTasks(telegramId);
    } catch (error) {} finally {
      setActiveTaskId(null);
    }
  };

  const getStatusLabel = (status: string) => {
    const labels: Record<string, string> = {
      'published': 'Опубликовано',
      'scheduled': 'Запланировано',
      'not_published': 'Не опубликовано',
      'in_progress': 'Публикуется',
      'failed': 'Ошибка'
    };
    return labels[status] || status;
  };

  const enabledAccounts = publishAccounts.filter((item) => item.enabled);
  const enabledByNetwork = enabledAccounts.reduce<Record<string, number>>((acc, item) => {
    const network = normalizeNetwork(item.channel_code);
    acc[network] = (acc[network] || 0) + 1;
    return acc;
  }, {});
  const uniqueizationSlots = Object.keys(enabledByNetwork).length
    ? Math.max(...Object.values(enabledByNetwork))
    : 0;
  const networkSummary = Object.entries(enabledByNetwork)
    .map(([network, count]) => `${network}: ${count}`)
    .join(' · ');

  const sectionMeta: Record<string, { title: string; actionLabel: string | null }> = {
    branding: { title: 'Брендинг', actionLabel: 'Сохранить' },
    channels: { title: 'Каналы', actionLabel: 'Сохранить' },
    planning: { title: 'Планирование', actionLabel: 'Сохранить' },
    queue: { title: 'Очередь', actionLabel: null },
  };

  const currentSection = sectionMeta[activeTab] || sectionMeta.branding;

  const handleHeaderAction = async () => {
    if (activeTab === 'branding') {
      await saveBrandingSettings();
      return;
    }
    if (activeTab === 'channels') {
      await saveDescriptions();
      flashSaved();
      return;
    }
    if (activeTab === 'planning') {
      await savePlanningSettings();
    }
  };

  return (
    <div className="min-h-screen pb-32 flex flex-col items-center">
      <header className="w-full bg-white px-4 py-3 flex items-center justify-between border-b sticky top-0 z-50">
        <div>
          <p className="text-[12px] uppercase tracking-[0.18em] text-[#8d96a5]">Content Studio</p>
          <h1 className="text-[17px] font-bold">{currentSection.title}</h1>
        </div>
        {currentSection.actionLabel ? (
          <button onClick={handleHeaderAction} disabled={loading || savingChannelSettings} className="text-[16px] font-semibold text-[#24a1de] disabled:opacity-50">
            {loading || savingChannelSettings ? '...' : saved ? 'Сохранено' : currentSection.actionLabel}
          </button>
        ) : (
          <button onClick={() => telegramId && loadTasks(telegramId)} className="text-[#24a1de]">
            <RefreshCcw size={18} />
          </button>
        )}
      </header>

      <main className="w-full max-w-2xl px-4 py-6">
        <div className="tg-card p-4 mb-4 space-y-3">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-[#707579]">Telegram ID</p>
            <p className="text-xs font-mono text-slate-700">{telegramId || 'не определен'}</p>
          </div>
          <div className="flex items-center gap-2">
            <input
              type="text"
              inputMode="numeric"
              className="input-field h-10 flex-1"
              placeholder="Введите ваш Telegram ID"
              value={telegramIdInput}
              onChange={(e) => setTelegramIdInput(e.target.value)}
            />
            <button
              onClick={applyTelegramId}
              className="h-10 px-4 bg-blue-50 text-[#24a1de] text-xs font-bold rounded-lg"
            >
              Применить
            </button>
          </div>
          {!window.Telegram?.WebApp?.initDataUnsafe?.user?.id && (
            <p className="text-[11px] text-[#707579]">
              Если открываете интерфейс не внутри Telegram Mini App, укажите Telegram ID вручную.
            </p>
          )}
        </div>

        <input
          ref={endingInputRef}
          type="file"
          accept="video/mp4,video/quicktime,video/webm,video/x-matroska"
          onChange={(e) => void handleEndingSelected(e)}
          className="hidden"
        />

        <AnimatePresence mode="wait">
          {activeTab === 'branding' && (
            <motion.div key="branding" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-6">
              <div className="tg-card p-4 bg-gradient-to-br from-slate-950 to-slate-800 text-white">
                <p className="text-[12px] uppercase tracking-[0.18em] text-slate-300">Зона бренда</p>
                <h2 className="text-[22px] font-bold mt-2">Плашка для роликов</h2>
                <p className="text-sm text-slate-300 mt-2">
                  Здесь хранится визуальный оверлей, который накладывается на каждый финальный ролик перед публикацией.
                </p>
              </div>
              <div className="tg-card overflow-hidden">
                <div className="p-4 border-b">
                  <h3 className="text-[15px] font-bold uppercase text-[#707579] tracking-tight">Наложение логотипа</h3>
                </div>
                <div className="p-0">
                  <button 
                    onClick={handlePickFile}
                    className="w-full flex items-center gap-4 p-4 hover:bg-slate-50 transition-colors active:bg-slate-100"
                  >
                    <div className="p-3 bg-blue-50 text-[#24a1de] rounded-xl">
                      <Upload size={20} />
                    </div>
                    <div className="flex-1 text-left">
                      <p className="font-semibold text-[16px]">{uploadingPlate ? 'Загрузка...' : 'Загрузить плашку'}</p>
                      <p className="text-xs text-[#707579]">{plateFile ? plateFile.name : 'PNG или WebP с прозрачностью'}</p>
                    </div>
                    <ChevronRight size={18} className="text-[#c7c7cc]" />
                  </button>
                  <input ref={fileInputRef} type="file" accept="image/png,image/webp" onChange={handlePlateSelected} className="hidden" />
                </div>
              </div>
              <div className="tg-card">
                <div className="p-4 border-b">
                  <h3 className="text-[15px] font-bold uppercase text-[#707579] tracking-tight">Момент появления</h3>
                </div>
                <div className="p-4 space-y-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-slate-900">Плашка стартует с {plateStartPercent}% ролика</p>
                      <p className="text-xs text-[#707579] mt-1">
                        0% покажет её сразу, 50% запустит с середины, 100% только в самом конце.
                      </p>
                    </div>
                    <div className="min-w-[64px] h-10 px-3 rounded-xl bg-slate-100 text-slate-900 font-bold text-sm flex items-center justify-center">
                      {plateStartPercent}%
                    </div>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    step={1}
                    value={plateStartPercent}
                    onChange={(e) => setPlateStartPercent(clampPercent(Number(e.target.value)))}
                    className="w-full accent-[#24a1de]"
                  />
                  <div className="flex justify-between text-[11px] uppercase tracking-wide text-[#9aa1ac]">
                    <span>С начала</span>
                    <span>С середины</span>
                    <span>С конца</span>
                  </div>
                </div>
              </div>
            </motion.div>
          )}

          {activeTab === 'channels' && (
            <motion.div key="channels" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-6">
              <div className="tg-card p-4 bg-gradient-to-br from-[#fff6e7] to-[#fffaf2] border border-[#f5dfb2]">
                <p className="text-[12px] uppercase tracking-[0.18em] text-[#9a6b13]">Публикация</p>
                <h2 className="text-[22px] font-bold mt-2 text-slate-900">Каналы и их материалы</h2>
                <p className="text-sm text-slate-600 mt-2">
                  У каждого аккаунта свой статус, своё описание и своя видео-концовка. Здесь настраивается именно то, что уйдёт в PostMyPost.
                </p>
              </div>
              <div className="tg-card overflow-hidden">
                 <div className="p-4 border-b flex items-center justify-between">
                    <h3 className="text-[15px] font-bold uppercase text-[#707579] tracking-tight">Каналы публикации</h3>
                    <div className="flex items-center gap-3">
                      <button onClick={() => telegramId && loadPublishAccounts(telegramId)} className="text-[#24a1de]"><RefreshCcw size={16} /></button>
                    </div>
                 </div>
                 {channelsError && (
                   <div className="px-4 py-3 text-xs text-red-600 bg-red-50 border-b border-red-100">{channelsError}</div>
                 )}
                 {!channelsError && (
                   <div className="px-4 py-3 text-xs text-[#4b5563] bg-slate-50 border-b border-slate-100">
                     {enabledAccounts.length > 0 ? (
                       <>
                         <p>Активные профили: {networkSummary}</p>
                         <p>Уникализаций будет: {uniqueizationSlots}. Каждый профиль получит свой финальный файл.</p>
                       </>
                     ) : (
                       <p>Включи хотя бы один профиль для публикации и распределения уникальных видео.</p>
                     )}
                   </div>
                 )}
                 <div className="divide-y">
                    {publishAccounts.map(acc => {
                      const currentEnding = getEndingForAccount(acc.account_id, acc.channel_code);
                      const network = normalizeNetwork(acc.channel_code);
                      const canUploadEnding = ['instagram', 'youtube', 'tiktok'].includes(network);
                      return (
                      <div key={acc.account_id} className="p-4 space-y-3">
                         <div className="flex items-center justify-between">
                           <div>
                              <p className="font-semibold text-[15px]">{acc.account_name}</p>
                              <p className="text-[12px] text-[#707579]">{acc.channel_name || 'Канал'} · {network}</p>
                           </div>
                           <button onClick={() => togglePublishAccount(acc.account_id)} className={`w-12 h-6 rounded-full transition-all flex items-center p-1 ${acc.enabled ? 'bg-[#34c759]' : 'bg-[#e9e9eb]'}`}>
                              <div className={`w-4 h-4 bg-white rounded-full shadow-sm transform transition-all ${acc.enabled ? 'translate-x-6' : 'translate-x-0'}`} />
                           </button>
                         </div>
                         <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 flex items-center gap-3">
                           <div className="p-2 rounded-lg bg-white text-slate-700 border border-slate-200">
                             <Video size={16} />
                           </div>
                           <div className="flex-1 min-w-0">
                             <p className="text-[11px] text-[#707579] uppercase tracking-wide">Видео концовка</p>
                             <p className="text-[13px] text-slate-800 truncate">
                               {currentEnding ? (currentEnding.label || currentEnding.file_path.split('/').pop()) : 'Не загружена'}
                             </p>
                           </div>
                           <button
                             onClick={() => handlePickEnding(acc)}
                             disabled={!canUploadEnding || uploadingEndingAccountId === acc.account_id}
                             className="h-9 px-3 bg-blue-50 text-[#24a1de] text-xs font-bold rounded-lg disabled:opacity-50"
                           >
                             {uploadingEndingAccountId === acc.account_id ? 'Загрузка...' : 'Загрузить'}
                           </button>
                         </div>
                         <label className="flex flex-col gap-1">
                           <span className="text-[11px] text-[#707579] uppercase tracking-wide">Описание для этого канала</span>
                           <textarea
                             rows={2}
                             className="input-field text-[13px] resize-y"
                             placeholder="Введите текст, который должен публиковаться в этом канале..."
                             value={channelDescriptions[acc.account_id] || ''}
                             onChange={(e) =>
                               setChannelDescriptions((prev) => ({
                                 ...prev,
                                 [acc.account_id]: e.target.value,
                               }))
                             }
                           />
                         </label>
                      </div>
                    )})}
                 </div>
              </div>
            </motion.div>
          )}

          {activeTab === 'planning' && (
            <motion.div key="planning" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-6">
              <div className="tg-card p-4 bg-gradient-to-br from-[#eef5ff] to-[#f8fbff] border border-[#cfe0ff]">
                <p className="text-[12px] uppercase tracking-[0.18em] text-[#3967b7]">Автопланирование</p>
                <h2 className="text-[22px] font-bold mt-2 text-slate-900">Правила публикации</h2>
                <p className="text-sm text-slate-600 mt-2">
                  Здесь задаётся дневной лимит и рабочее окно по Москве. Новые ролики получают время автоматически и равномерно.
                </p>
              </div>
              <div className="tg-card">
                <div className="p-4 border-b">
                  <h3 className="text-[15px] font-bold uppercase text-[#707579] tracking-tight">Авторасписание (МСК)</h3>
                </div>
                <div className="p-4 space-y-4">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-[#707579]">Включить автопланирование</span>
                    <button
                      onClick={() => setAutoScheduleEnabled((prev) => !prev)}
                      className={`w-12 h-6 rounded-full transition-all flex items-center p-1 ${autoScheduleEnabled ? 'bg-[#34c759]' : 'bg-[#e9e9eb]'}`}
                    >
                      <div className={`w-4 h-4 bg-white rounded-full shadow-sm transform transition-all ${autoScheduleEnabled ? 'translate-x-6' : 'translate-x-0'}`} />
                    </button>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <label className="flex flex-col gap-1">
                      <span className="text-xs text-[#707579]">Лимит в день</span>
                      <input
                        type="number"
                        min={1}
                        max={96}
                        value={publishLimitPerDay}
                        onChange={(e) => setPublishLimitPerDay(Math.max(1, Math.min(96, Number(e.target.value) || 1)))}
                        className="input-field h-10"
                        disabled={!autoScheduleEnabled}
                      />
                    </label>
                    <label className="flex flex-col gap-1">
                      <span className="text-xs text-[#707579]">С (МСК)</span>
                      <input
                        type="time"
                        step={1}
                        value={publishWindowStartMsk}
                        onChange={(e) => setPublishWindowStartMsk(e.target.value || '10:00:00')}
                        className="input-field h-10"
                        disabled={!autoScheduleEnabled}
                      />
                    </label>
                    <label className="flex flex-col gap-1">
                      <span className="text-xs text-[#707579]">До (МСК)</span>
                      <input
                        type="time"
                        step={1}
                        value={publishWindowEndMsk}
                        onChange={(e) => setPublishWindowEndMsk(e.target.value || '22:00:00')}
                        className="input-field h-10"
                        disabled={!autoScheduleEnabled}
                      />
                    </label>
                  </div>
                  <p className="text-xs text-[#707579]">
                    Новые ролики будут автоматически ставиться в очередь по Москве с равномерным шагом и точностью до секунды.
                  </p>
                </div>
              </div>
            </motion.div>
          )}

          {activeTab === 'queue' && (
            <motion.div key="queue" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-6">
              <div className="tg-card p-4 bg-gradient-to-br from-[#f5f7fa] to-[#ffffff] border border-slate-200">
                <p className="text-[12px] uppercase tracking-[0.18em] text-slate-500">Мониторинг</p>
                <h2 className="text-[22px] font-bold mt-2 text-slate-900">Очередь публикаций</h2>
                <p className="text-sm text-slate-600 mt-2">
                  Здесь только задачи: статус обработки, ручная дата публикации и скачивание готового файла, если он ещё доступен локально.
                </p>
              </div>
              <div className="tg-card">
                <div className="p-4 border-b flex items-center justify-between">
                  <h3 className="text-[15px] font-bold uppercase text-[#707579] tracking-tight">Очередь публикаций</h3>
                  <button onClick={() => telegramId && loadTasks(telegramId)} className="text-[#24a1de]"><RefreshCcw size={16} /></button>
                </div>
                <div className="divide-y overflow-auto max-h-[500px]">
                  {tasks.map(task => (
                    <div key={task.id} className="p-4 space-y-3">
                       <div className="flex justify-between items-start">
                          <div className="flex-1 min-w-0 mr-4">
                             <p className="text-xs font-bold text-[#707579] uppercase truncate">ID #{task.id} · {task.status}</p>
                             <p className="text-sm font-medium text-slate-900 truncate mt-1">{task.source_url}</p>
                          </div>
                          <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full uppercase ${task.publishing_status === 'published' ? 'bg-green-100 text-green-600' : 'bg-blue-100 text-blue-600'}`}>
                             {getStatusLabel(task.publishing_status)}
                          </span>
                       </div>
                       <div className="flex gap-2">
                          <input
                            type="datetime-local"
                            value={scheduleInputs[task.id] || ''}
                            onChange={(e) => setScheduleInputs(prev => ({ ...prev, [task.id]: e.target.value }))}
                            className="input-field text-xs h-9 flex-1 py-1"
                          />
                          <button 
                            onClick={() => saveTaskSchedule(task.id)}
                            className="h-9 px-4 bg-blue-50 text-[#24a1de] text-xs font-bold rounded-lg"
                          >
                            Задать
                          </button>
                          {task.output_path && task.status === 'completed' && (
                            <a
                              href={`${API_BASE}/tasks/${telegramId}/${task.id}/file`}
                              target="_blank"
                              rel="noreferrer"
                              className="h-9 px-4 bg-green-50 text-green-700 text-xs font-bold rounded-lg inline-flex items-center"
                            >
                              Скачать
                            </a>
                          )}
                       </div>
                    </div>
                  ))}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </main>

      {/* Floating Preview Toggle */}
      {activeTab === 'branding' && (
        <button onClick={() => setShowPreview(true)} className="fab-preview">
          <Eye size={24} />
        </button>
      )}

      {/* Preview Overlay */}
      <AnimatePresence>
        {showPreview && (
          <motion.div 
            initial={{ opacity: 0 }} 
            animate={{ opacity: 1 }} 
            exit={{ opacity: 0 }}
            className="preview-overlay"
          >
            <button onClick={() => setShowPreview(false)} className="close-btn">
               <X size={24} />
            </button>
            
            <div className="phone-frame mt-8">
              <div className="phone-notch"></div>
              
              <div className="absolute inset-0 bg-[#e9e9eb]">
                <div className="absolute inset-0 bg-[url('https://images.unsplash.com/photo-1518173946687-a4c8a9b746f5?auto=format&fit=crop&q=80')] bg-cover bg-center opacity-60 grayscale-[0.2]" />
                <div className="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-black/20 to-transparent" />
              </div>

              <div className="absolute top-10 right-6 z-20">
                {platePreviewUrl ? (
                  <img src={platePreviewUrl} className="max-w-[70px] h-auto drop-shadow-md" />
                ) : (
                  <div className="w-12 h-12 bg-white/30 backdrop-blur rounded flex items-center justify-center border border-white/20">
                    <ImageIcon className="text-white/40" size={16} />
                  </div>
                )}
              </div>

              <div className="absolute inset-0 flex items-center justify-center px-4 pointer-events-none z-20">
                <div
                  style={{ color: '#ffffff', textShadow: '0 2px 4px rgba(0,0,0,0.3)' }}
                  className="text-center font-black uppercase leading-[1.1] text-[8vw]"
                >
                  Создавай Быстро<br />Публикуй Легко
                </div>
              </div>

              <div className="absolute bottom-10 left-6 right-6 flex items-end justify-between z-20">
                 <div className="flex items-center gap-2">
                    <div className="w-6 h-6 rounded-full bg-white/40 backdrop-blur border border-white/30" />
                    <div className="space-y-1">
                       <div className="w-16 h-1 bg-white/40 rounded" />
                       <div className="w-10 h-0.5 bg-white/20 rounded" />
                    </div>
                 </div>
                 <div className="w-6 h-6 rounded-full border border-white/40 flex items-center justify-center">
                    <div className="w-2 h-2 rounded-sm bg-white/40" />
                 </div>
              </div>
            </div>
            <div className="mt-4 space-y-2 flex flex-col items-center">
              <p className="text-[11px] font-bold text-white uppercase tracking-widest bg-black/20 px-3 py-1 rounded-full backdrop-blur-sm">
                Предпросмотр активен
              </p>
              <div className="w-[220px] max-w-full rounded-full bg-white/15 overflow-hidden">
                <div
                  className="h-1.5 bg-white/80"
                  style={{ width: `${plateStartPercent}%` }}
                />
              </div>
              <p className="text-[11px] text-white/85">
                Плашка начнёт появляться с {plateStartPercent}% хронометража ролика.
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <nav className="bottom-nav">
        {[
          { id: 'branding', icon: ImageIcon, label: 'Брендинг' },
          { id: 'channels', icon: LayoutGrid, label: 'Каналы' },
          { id: 'planning', icon: CalendarClock, label: 'План' },
          { id: 'queue', icon: RefreshCcw, label: 'Очередь' }
        ].map(tab => (
          <button 
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`nav-item ${activeTab === tab.id ? 'active' : ''}`}
          >
            <tab.icon size={22} />
            <span className="nav-label">{tab.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
};

export default App;
