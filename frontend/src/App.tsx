import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Image as ImageIcon,
  Video,
  Upload,
  CalendarClock,
  RefreshCcw,
  LayoutGrid,
  ChevronRight,
  Search,
  CalendarDays,
  Clock3,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Download,
  Trash2,
  Globe2,
  PlaySquare,
  Camera,
  Music2,
} from 'lucide-react';
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
  target_account_id?: number | null;
  target_platform?: string | null;
  preview_url?: string | null;
  publish_at?: string | null;
  publishing_status: string;
  created_at: string;
  updated_at: string;
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
  selected_plate_id?: number | null;
  selected_plate_ids?: number[];
  plate_start_percent?: number | null;
  plate_file_path?: string | null;
  plate_assets?: PlateAsset[];
};

type EndingClip = {
  id: number;
  user_id: number;
  account_id?: number | null;
  file_path: string;
  label?: string | null;
  platform: string;
};

type PlateAsset = {
  id: number;
  file_path: string;
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
const ACTIVE_TAB_STORAGE_KEY = 'content_studio_active_tab';

const normalizeTelegramId = (value: unknown): string => {
  const text = String(value ?? '').trim();
  return /^\d{5,20}$/.test(text) ? text : '';
};

const getTelegramIdFromInitDataHash = (): string => {
  const hash = String(window.location.hash || '').replace(/^#/, '');
  if (!hash) return '';

  const webAppParams = new URLSearchParams(hash);
  const rawInitData = webAppParams.get('tgWebAppData');
  if (!rawInitData) return '';

  try {
    const initData = new URLSearchParams(rawInitData);
    const rawUser = initData.get('user');
    if (!rawUser) return '';

    const user = JSON.parse(rawUser) as { id?: number | string };
    return normalizeTelegramId(user?.id);
  } catch {
    return '';
  }
};

const clampPercent = (value: number) => Math.max(0, Math.min(100, Math.round(value)));
const cleanTaskSource = (value: string) =>
  String(value || '')
    .split(' [slot ', 1)[0]
    .split(' [variant ', 1)[0]
    .split(' [account ', 1)[0]
    .trim();

const formatDateTimeLabel = (value?: string | null) => {
  if (!value) return 'Не назначено';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Не назначено';
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
};

const isImagePreview = (value?: string | null) => /\.(jpg|jpeg|png|webp|gif)(\?.*)?$/i.test(String(value || ''));

const App = () => {
  const [activeTab, setActiveTab] = useState(() => {
    const stored = window.localStorage.getItem(ACTIVE_TAB_STORAGE_KEY);
    return stored === 'channels' || stored === 'planning' || stored === 'queue' ? stored : 'queue';
  });
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);

  const [autoScheduleEnabled, setAutoScheduleEnabled] = useState(false);
  const [publishLimitPerDay, setPublishLimitPerDay] = useState(3);
  const [publishWindowStartMsk, setPublishWindowStartMsk] = useState('10:00:00');
  const [publishWindowEndMsk, setPublishWindowEndMsk] = useState('22:00:00');
  const [telegramId, setTelegramId] = useState('');
  const [telegramIdInput, setTelegramIdInput] = useState('');
  const [tasks, setTasks] = useState<VideoTaskItem[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [queueStatusFilter, setQueueStatusFilter] = useState<'all' | 'active' | 'scheduled' | 'published' | 'failed'>('all');
  const [queuePlatformFilter, setQueuePlatformFilter] = useState<'all' | 'instagram' | 'youtube' | 'tiktok' | 'other'>('all');
  const [queueSearch, setQueueSearch] = useState('');
  const [scheduleInputs, setScheduleInputs] = useState<Record<number, string>>({});
  const [activeTaskId, setActiveTaskId] = useState<number | null>(null);
  const [deletingTaskId, setDeletingTaskId] = useState<number | null>(null);
  const [publishAccounts, setPublishAccounts] = useState<PublishAccount[]>([]);
  const [channelDescriptions, setChannelDescriptions] = useState<Record<number, string>>({});
  const [channelsLoading, setChannelsLoading] = useState(false);
  const [channelsError, setChannelsError] = useState('');
  const [savingChannelSettings, setSavingChannelSettings] = useState(false);
  const [selectedPlateIdsByAccount, setSelectedPlateIdsByAccount] = useState<Record<number, number[]>>({});
  const [plateStartPercentByAccount, setPlateStartPercentByAccount] = useState<Record<number, number>>({});
  const [plateUploadTarget, setPlateUploadTarget] = useState<PublishAccount | null>(null);
  const [uploadingPlateAccountId, setUploadingPlateAccountId] = useState<number | null>(null);
  const [endingClips, setEndingClips] = useState<EndingClip[]>([]);
  const [uploadingEndingAccountId, setUploadingEndingAccountId] = useState<number | null>(null);
  const [endingUploadTarget, setEndingUploadTarget] = useState<PublishAccount | null>(null);
  const [deletingPlateId, setDeletingPlateId] = useState<number | null>(null);
  const [deletingEndingId, setDeletingEndingId] = useState<number | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const endingInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    window.localStorage.setItem(ACTIVE_TAB_STORAGE_KEY, activeTab);
  }, [activeTab]);

  useEffect(() => {
    const webApp = window.Telegram?.WebApp;
    if (webApp?.ready) webApp.ready();
    if (webApp?.expand) webApp.expand();

    const tgUserId = normalizeTelegramId(webApp?.initDataUnsafe?.user?.id);
    const hashId = getTelegramIdFromInitDataHash();
    const query = new URLSearchParams(window.location.search);
    const queryId = normalizeTelegramId(query.get('telegram_id') || query.get('tg_id'));
    const storedId = normalizeTelegramId(window.localStorage.getItem(TELEGRAM_ID_STORAGE_KEY));
    const resolvedId = tgUserId || hashId || queryId || storedId;
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
      const response = await axios.get<PublishAccount[]>(`${API_BASE}/postmypost/channels/${targetTelegramId}`, {
        timeout: 15000,
      });
      setPublishAccounts(response.data);
      setChannelDescriptions(
        response.data.reduce<Record<number, string>>((acc, item) => {
          acc[item.account_id] = item.description || '';
          return acc;
        }, {}),
      );
      setSelectedPlateIdsByAccount(
        response.data.reduce<Record<number, number[]>>((acc, item) => {
          const ids = Array.isArray(item.selected_plate_ids)
            ? item.selected_plate_ids
            : item.selected_plate_id
              ? [item.selected_plate_id]
              : [];
          acc[item.account_id] = ids;
          return acc;
        }, {}),
      );
      setPlateStartPercentByAccount(
        response.data.reduce<Record<number, number>>((acc, item) => {
          acc[item.account_id] = clampPercent(item.plate_start_percent ?? 0);
          return acc;
        }, {}),
      );
      setChannelsError('');
    } catch (error: any) {
      const detail = error?.response?.data?.detail;
      if (error?.response?.status === 403) {
        setChannelsError('Доступ запрещен. Ваш Telegram ID не добавлен в список администраторов в .env файле.');
      } else if (detail) {
        setChannelsError(String(detail));
      } else {
        setChannelsError('Не удалось загрузить каналы из PostMyPost. Проверьте соединение с сервером.');
      }
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

  const getEndingsForAccount = (accountId: number, platform?: string | null) => {
    const exact = endingClips.filter((item) => item.account_id === accountId);
    if (exact.length > 0) return exact;
    const normalizedPlatform = normalizeNetwork(platform);
    return endingClips.filter((item) => !item.account_id && normalizeNetwork(item.platform) === normalizedPlatform);
  };

  const buildDescriptionsPayload = (source: Record<number, string>) => {
    return Object.entries(source).reduce<Record<string, string>>((acc, [accountId, value]) => {
      const text = (value || '').trim();
      if (!text) return acc;
      acc[accountId] = text;
      return acc;
    }, {});
  };

  const buildPlateIdsPayload = (source: Record<number, number[]>) =>
    Object.entries(source).reduce<Record<string, number[]>>((acc, [accountId, value]) => {
      acc[accountId] = Array.isArray(value) ? value : [];
      return acc;
    }, {});

  const buildPlatePercentsPayload = (source: Record<number, number>) =>
    Object.entries(source).reduce<Record<string, number>>((acc, [accountId, value]) => {
      acc[accountId] = clampPercent(Number(value) || 0);
      return acc;
    }, {});

  const savePublishChannelSettings = async (
    accounts: PublishAccount[],
    descriptions: Record<number, string>,
    plateIds: Record<number, number[]>,
    platePercents: Record<number, number>,
  ) => {
    if (!telegramId) return;
    const accountIds = accounts.filter((item) => item.enabled).map((item) => item.account_id);
    const payload = {
      account_ids: accountIds,
      descriptions: buildDescriptionsPayload(descriptions),
      selected_plate_ids: buildPlateIdsPayload(plateIds),
      plate_start_percents: buildPlatePercentsPayload(platePercents),
    };
    const response = await axios.post<PublishAccount[]>(`${API_BASE}/postmypost/channels/${telegramId}`, payload, {
      timeout: 20000,
    });
    setPublishAccounts(response.data);
    setChannelDescriptions(
      response.data.reduce<Record<number, string>>((acc, item) => {
        acc[item.account_id] = item.description || '';
        return acc;
      }, {}),
    );
    setSelectedPlateIdsByAccount(
      response.data.reduce<Record<number, number[]>>((acc, item) => {
        const ids = Array.isArray(item.selected_plate_ids)
          ? item.selected_plate_ids
          : item.selected_plate_id
            ? [item.selected_plate_id]
            : [];
        acc[item.account_id] = ids;
        return acc;
      }, {}),
    );
    setPlateStartPercentByAccount(
      response.data.reduce<Record<number, number>>((acc, item) => {
        acc[item.account_id] = clampPercent(item.plate_start_percent ?? 0);
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
      await savePublishChannelSettings(nextAccounts, channelDescriptions, selectedPlateIdsByAccount, plateStartPercentByAccount);
    } catch (error) {}
  };

  const saveChannelSettings = async () => {
    if (!telegramId) return;
    setSavingChannelSettings(true);
    try {
      await savePublishChannelSettings(publishAccounts, channelDescriptions, selectedPlateIdsByAccount, plateStartPercentByAccount);
    } catch (error) {
    } finally {
      setSavingChannelSettings(false);
    }
  };

  useEffect(() => {
    if (!telegramId) return;
    void loadTasks(telegramId);
  }, [telegramId]);

  useEffect(() => {
    if (!telegramId || activeTab !== 'channels') return;
    if (publishAccounts.length > 0 && endingClips.length > 0) return;
    void loadPublishAccounts(telegramId);
    void loadEndingClips(telegramId);
  }, [telegramId, activeTab]);

  const handlePickPlate = (account: PublishAccount) => {
    setPlateUploadTarget(account);
    fileInputRef.current?.click();
  };

  const handlePlateSelected = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    if (files.length === 0 || !telegramId || !plateUploadTarget) return;
    setUploadingPlateAccountId(plateUploadTarget.account_id);
    try {
      const uploadedAssets: PlateAsset[] = [];
      for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);
        const response = await axios.post<PlateAsset>(`${API_BASE}/upload/plate/${telegramId}`, formData);
        uploadedAssets.push(response.data);
      }
      const uploadedIds = uploadedAssets.map((item) => item.id);
      setSelectedPlateIdsByAccount((prev) => {
        const current = prev[plateUploadTarget.account_id] || [];
        return {
          ...prev,
          [plateUploadTarget.account_id]: Array.from(new Set([...current, ...uploadedIds])),
        };
      });
      setPublishAccounts((prev) =>
        prev.map((item) => {
          if (item.account_id !== plateUploadTarget.account_id) return item;
          const currentAssets = item.plate_assets || [];
          const mergedAssets = [...currentAssets];
          for (const asset of uploadedAssets) {
            if (!mergedAssets.some((existing) => existing.id === asset.id)) {
              mergedAssets.push(asset);
            }
          }
          const currentIds = item.selected_plate_ids || (item.selected_plate_id ? [item.selected_plate_id] : []);
          return {
            ...item,
            selected_plate_ids: Array.from(new Set([...currentIds, ...uploadedIds])),
            selected_plate_id: currentIds[0] || uploadedIds[0] || null,
            plate_assets: mergedAssets,
            plate_file_path: (mergedAssets[0] || uploadedAssets[0])?.file_path || item.plate_file_path || null,
          };
        }),
      );
    } catch (error) {} finally {
      setUploadingPlateAccountId(null);
      setPlateUploadTarget(null);
      event.target.value = '';
    }
  };

  const handlePickEnding = (account: PublishAccount) => {
    setEndingUploadTarget(account);
    endingInputRef.current?.click();
  };

  const handleEndingSelected = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    if (files.length === 0 || !telegramId || !endingUploadTarget) return;
    const platform = normalizeNetwork(endingUploadTarget.channel_code);
    if (!['instagram', 'youtube', 'tiktok'].includes(platform)) return;
    setUploadingEndingAccountId(endingUploadTarget.account_id);
    try {
      const uploadedEndings: EndingClip[] = [];
      for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('platform', platform);
        formData.append('label', file.name);
        formData.append('account_id', String(endingUploadTarget.account_id));
        const response = await axios.post<EndingClip>(`${API_BASE}/upload/ending/${telegramId}`, formData);
        uploadedEndings.push(response.data);
      }
      setEndingClips((prev) => [...uploadedEndings, ...prev]);
    } catch (error) {
    } finally {
      setUploadingEndingAccountId(null);
      setEndingUploadTarget(null);
      event.target.value = '';
    }
  };

  const handleDeletePlate = async (plateId: number) => {
    if (!telegramId) return;
    setDeletingPlateId(plateId);
    try {
      await axios.delete(`${API_BASE}/plates/${telegramId}/${plateId}`);
      await loadPublishAccounts(telegramId);
    } catch (error) {
    } finally {
      setDeletingPlateId(null);
    }
  };

  const handleDeleteEnding = async (endingId: number) => {
    if (!telegramId) return;
    setDeletingEndingId(endingId);
    try {
      await axios.delete(`${API_BASE}/endings/${telegramId}/${endingId}`);
      await loadEndingClips(telegramId);
    } catch (error) {
    } finally {
      setDeletingEndingId(null);
    }
  };

  const flashSaved = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
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

  const removeTaskFromQueue = async (taskId: number) => {
    if (!telegramId) return;
    setDeletingTaskId(taskId);
    try {
      await axios.delete(`${API_BASE}/tasks/${telegramId}/${taskId}`);
      setTasks((prev) => prev.filter((item) => item.id !== taskId));
      setScheduleInputs((prev) => {
        const next = { ...prev };
        delete next[taskId];
        return next;
      });
      await loadTasks(telegramId);
    } catch (error) {
    } finally {
      setDeletingTaskId(null);
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

  const getProcessingLabel = (status: string) => {
    const labels: Record<string, string> = {
      pending: 'В очереди',
      processing: 'Обработка',
      completed: 'Готово',
      failed: 'Ошибка',
    };
    return labels[status] || status;
  };

  const getProcessingTone = (status: string) => {
    const tones: Record<string, string> = {
      pending: 'bg-slate-100 text-slate-600 border-slate-200',
      processing: 'bg-amber-100 text-amber-700 border-amber-200',
      completed: 'bg-emerald-100 text-emerald-700 border-emerald-200',
      failed: 'bg-rose-100 text-rose-700 border-rose-200',
    };
    return tones[status] || 'bg-slate-100 text-slate-600 border-slate-200';
  };

  const getPublicationTone = (status: string) => {
    const tones: Record<string, string> = {
      published: 'bg-emerald-100 text-emerald-700 border-emerald-200',
      scheduled: 'bg-sky-100 text-sky-700 border-sky-200',
      not_published: 'bg-slate-100 text-slate-600 border-slate-200',
      in_progress: 'bg-violet-100 text-violet-700 border-violet-200',
      failed: 'bg-rose-100 text-rose-700 border-rose-200',
    };
    return tones[status] || 'bg-slate-100 text-slate-600 border-slate-200';
  };

  const getPlatformMeta = (platform: string) => {
    if (platform === 'youtube') {
      return {
        label: 'YouTube',
        tone: 'bg-rose-100 text-rose-700 border-rose-200',
        icon: <PlaySquare size={14} />,
      };
    }
    if (platform === 'instagram') {
      return {
        label: 'Instagram',
        tone: 'bg-fuchsia-100 text-fuchsia-700 border-fuchsia-200',
        icon: <Camera size={14} />,
      };
    }
    if (platform === 'tiktok') {
      return {
        label: 'TikTok',
        tone: 'bg-cyan-100 text-cyan-700 border-cyan-200',
        icon: <Music2 size={14} />,
      };
    }
    return {
      label: 'Другое',
      tone: 'bg-slate-100 text-slate-700 border-slate-200',
      icon: <Globe2 size={14} />,
    };
  };

  const getTaskDisplayTitle = (task: VideoTaskItem) => {
    const source = cleanTaskSource(task.source_url);
    if (task.type === 'youtube' && /^[A-Za-z0-9_-]{11}$/.test(source)) {
      return `YouTube video ${source}`;
    }
    try {
      const parsed = new URL(source);
      const host = parsed.hostname.replace(/^www\./, '');
      const path = `${parsed.pathname}${parsed.search}`.replace(/\/$/, '') || '/';
      return `${host}${path}`;
    } catch {
      return source || `Задача #${task.id}`;
    }
  };

  const getTaskSourceHint = (task: VideoTaskItem) => {
    const labels: Record<string, string> = {
      youtube: 'Источник: YouTube',
      instagram: 'Источник: Instagram',
      vizard: 'Источник: Vizard',
    };
    return labels[task.type] || `Источник: ${task.type}`;
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
    channels: { title: 'Каналы', actionLabel: 'Сохранить' },
    planning: { title: 'Планирование', actionLabel: 'Сохранить' },
    queue: { title: 'Очередь', actionLabel: null },
  };

  const currentSection = sectionMeta[activeTab] || sectionMeta.channels;
  const accountsById = publishAccounts.reduce<Record<number, PublishAccount>>((acc, account) => {
    acc[account.account_id] = account;
    return acc;
  }, {});
  const queueStatusOptions: Array<{ id: 'all' | 'active' | 'scheduled' | 'published' | 'failed'; label: string }> = [
    { id: 'all', label: 'Все' },
    { id: 'active', label: 'В работе' },
    { id: 'scheduled', label: 'Запланировано' },
    { id: 'published', label: 'Опубликовано' },
    { id: 'failed', label: 'Ошибки' },
  ];
  const queuePlatformOptions: Array<{ id: 'all' | 'instagram' | 'youtube' | 'tiktok' | 'other'; label: string }> = [
    { id: 'all', label: 'Все платформы' },
    { id: 'youtube', label: 'YouTube' },
    { id: 'instagram', label: 'Instagram' },
    { id: 'tiktok', label: 'TikTok' },
    { id: 'other', label: 'Другое' },
  ];
  const platformFilteredTasks = tasks.filter((task) => {
    const account = task.target_account_id ? accountsById[task.target_account_id] : undefined;
    const platform = normalizeNetwork(task.target_platform || account?.channel_code || task.type);
    return queuePlatformFilter === 'all' || platform === queuePlatformFilter;
  });
  const queueCounters = {
    all: platformFilteredTasks.length,
    active: platformFilteredTasks.filter((task) => ['pending', 'processing', 'in_progress'].includes(task.status) || task.publishing_status === 'in_progress').length,
    scheduled: platformFilteredTasks.filter((task) => task.publishing_status === 'scheduled').length,
    published: platformFilteredTasks.filter((task) => task.publishing_status === 'published').length,
    failed: platformFilteredTasks.filter((task) => task.status === 'failed' || task.publishing_status === 'failed').length,
  };
  const filteredTasks = tasks.filter((task) => {
    const account = task.target_account_id ? accountsById[task.target_account_id] : undefined;
    const platform = normalizeNetwork(task.target_platform || account?.channel_code || task.type);
    const title = getTaskDisplayTitle(task).toLowerCase();
    const searchable = [
      title,
      cleanTaskSource(task.source_url).toLowerCase(),
      account?.account_name?.toLowerCase() || '',
      account?.channel_name?.toLowerCase() || '',
      platform,
    ].join(' ');

    const matchesSearch = !queueSearch.trim() || searchable.includes(queueSearch.trim().toLowerCase());
    const matchesPlatform = queuePlatformFilter === 'all' || platform === queuePlatformFilter;
    const matchesStatus =
      queueStatusFilter === 'all' ||
      (queueStatusFilter === 'active' &&
        (['pending', 'processing'].includes(task.status) || task.publishing_status === 'in_progress')) ||
      (queueStatusFilter === 'scheduled' && task.publishing_status === 'scheduled') ||
      (queueStatusFilter === 'published' && task.publishing_status === 'published') ||
      (queueStatusFilter === 'failed' && (task.status === 'failed' || task.publishing_status === 'failed'));

    return matchesSearch && matchesPlatform && matchesStatus;
  });

  const handleHeaderAction = async () => {
    if (activeTab === 'channels') {
      await saveChannelSettings();
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
          {!telegramId && (
            <>
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
              <p className="text-[11px] text-[#707579]">
                Если Mini App открыт из Telegram, ID подставляется автоматически. Ручной ввод нужен только как fallback.
              </p>
            </>
          )}
        </div>

        <input
          ref={endingInputRef}
          type="file"
          multiple
          accept="video/mp4,video/quicktime,video/webm,video/x-matroska"
          onChange={(e) => void handleEndingSelected(e)}
          className="hidden"
        />

        <AnimatePresence mode="wait">
          {activeTab === 'channels' && (
            <motion.div key="channels" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-6">
              <div className="tg-card p-4 bg-gradient-to-br from-[#fff6e7] to-[#fffaf2] border border-[#f5dfb2]">
                <p className="text-[12px] uppercase tracking-[0.18em] text-[#9a6b13]">Публикация</p>
                <h2 className="text-[22px] font-bold mt-2 text-slate-900">Каналы и их материалы</h2>
                <p className="text-sm text-slate-600 mt-2">
                  У каждого аккаунта свои описание, концовка и плашка. Здесь настраивается всё, что попадёт в финальный ролик и уйдёт в PostMyPost.
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
                      const currentEndings = getEndingsForAccount(acc.account_id, acc.channel_code);
                      const network = normalizeNetwork(acc.channel_code);
                      const canUploadEnding = ['instagram', 'youtube', 'tiktok'].includes(network);
                      const platePercent = plateStartPercentByAccount[acc.account_id] ?? 0;
                      const selectedPlateIds = selectedPlateIdsByAccount[acc.account_id] || [];
                      const plateAssets = acc.plate_assets || [];
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
                         <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 space-y-3">
                           <div className="flex items-center gap-3">
                             <div className="p-2 rounded-lg bg-white text-slate-700 border border-slate-200">
                               <Video size={16} />
                             </div>
                             <div className="flex-1 min-w-0">
                               <p className="text-[11px] text-[#707579] uppercase tracking-wide">Видео концовка</p>
                               <p className="text-[13px] text-slate-800">
                                 {currentEndings.length > 0 ? `Случайный выбор из ${currentEndings.length} файлов` : 'Не загружена'}
                               </p>
                             </div>
                             <button
                               onClick={() => handlePickEnding(acc)}
                               disabled={!canUploadEnding || uploadingEndingAccountId === acc.account_id}
                               className="h-9 px-3 bg-blue-50 text-[#24a1de] text-xs font-bold rounded-lg disabled:opacity-50"
                             >
                               {uploadingEndingAccountId === acc.account_id ? 'Загрузка...' : 'Добавить'}
                             </button>
                           </div>
                           <div className="space-y-2">
                             {currentEndings.length > 0 ? currentEndings.map((ending) => (
                               <div key={ending.id} className="flex items-center gap-2 rounded-xl bg-white border border-slate-200 px-3 py-2">
                                 <div className="min-w-0 flex-1">
                                   <p className="text-[12px] font-medium text-slate-900 truncate">
                                     {ending.label || ending.file_path.split('/').pop()}
                                   </p>
                                   <p className="text-[11px] text-[#707579]">#{ending.id}</p>
                                 </div>
                                 <button
                                   onClick={() => void handleDeleteEnding(ending.id)}
                                   disabled={deletingEndingId === ending.id}
                                   className="h-8 px-3 rounded-lg bg-rose-50 text-rose-600 text-[11px] font-bold disabled:opacity-50"
                                 >
                                   {deletingEndingId === ending.id ? '...' : 'Удалить'}
                                 </button>
                               </div>
                             )) : (
                               <p className="text-[12px] text-[#707579]">Файлы концовки ещё не добавлены.</p>
                             )}
                           </div>
                         </div>
                         <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 space-y-3">
                           <div className="flex items-center gap-3">
                             <div className="p-2 rounded-lg bg-white text-slate-700 border border-slate-200">
                               <ImageIcon size={16} />
                             </div>
                             <div className="flex-1 min-w-0">
                               <p className="text-[11px] text-[#707579] uppercase tracking-wide">Плашка канала</p>
                               <p className="text-[13px] text-slate-800">
                                 {selectedPlateIds.length > 0 ? `Случайный выбор из ${selectedPlateIds.length} файлов` : 'Не загружена'}
                               </p>
                             </div>
                             <button
                               onClick={() => handlePickPlate(acc)}
                               disabled={uploadingPlateAccountId === acc.account_id}
                               className="h-9 px-3 bg-blue-50 text-[#24a1de] text-xs font-bold rounded-lg disabled:opacity-50"
                             >
                               {uploadingPlateAccountId === acc.account_id ? 'Загрузка...' : 'Добавить'}
                             </button>
                           </div>
                           <div className="space-y-2">
                             {plateAssets.length > 0 ? plateAssets.map((asset) => (
                               <div key={asset.id} className="flex items-center gap-2 rounded-xl bg-white border border-slate-200 px-3 py-2">
                                 <div className="min-w-0 flex-1">
                                   <p className="text-[12px] font-medium text-slate-900 truncate">
                                     {asset.file_path.split('/').pop()}
                                   </p>
                                   <p className="text-[11px] text-[#707579]">#{asset.id}</p>
                                 </div>
                                 <button
                                   onClick={() => void handleDeletePlate(asset.id)}
                                   disabled={deletingPlateId === asset.id}
                                   className="h-8 px-3 rounded-lg bg-rose-50 text-rose-600 text-[11px] font-bold disabled:opacity-50"
                                 >
                                   {deletingPlateId === asset.id ? '...' : 'Удалить'}
                                 </button>
                               </div>
                             )) : (
                               <p className="text-[12px] text-[#707579]">Файлы плашки ещё не добавлены.</p>
                             )}
                           </div>
                           <div className="space-y-2">
                             <div className="flex items-center justify-between gap-3">
                               <div>
                                 <p className="text-[12px] font-semibold text-slate-900">Появление с {platePercent}%</p>
                                 <p className="text-[11px] text-[#707579]">0% сразу, 50% с середины, 100% в конце.</p>
                               </div>
                               <div className="min-w-[58px] h-9 px-3 rounded-xl bg-white text-slate-900 font-bold text-xs flex items-center justify-center border border-slate-200">
                                 {platePercent}%
                               </div>
                             </div>
                             <input
                               type="range"
                               min={0}
                               max={100}
                               step={1}
                               value={platePercent}
                               onChange={(e) =>
                                 setPlateStartPercentByAccount((prev) => ({
                                   ...prev,
                                   [acc.account_id]: clampPercent(Number(e.target.value)),
                                 }))
                               }
                               className="w-full accent-[#24a1de]"
                             />
                           </div>
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
                 <input ref={fileInputRef} type="file" multiple accept="image/png,image/webp" onChange={handlePlateSelected} className="hidden" />
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
                  Здесь видны превью, площадка публикации, статус обработки, время выхода и быстрые действия по каждому ролику.
                </p>
              </div>
              <div className="tg-card p-4 space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_220px] gap-3">
                  <label className="flex flex-col gap-1">
                    <span className="text-[11px] text-[#707579] uppercase tracking-wide">Поиск по ролику или каналу</span>
                    <div className="relative">
                      <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#9aa1ac]" />
                      <input
                        type="text"
                        value={queueSearch}
                        onChange={(e) => setQueueSearch(e.target.value)}
                        placeholder="Например: YouTube, Instagram, канал или ID"
                        className="input-field h-10 w-full pl-10"
                      />
                    </div>
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-[11px] text-[#707579] uppercase tracking-wide">Платформа</span>
                    <select
                      value={queuePlatformFilter}
                      onChange={(e) => setQueuePlatformFilter(e.target.value as typeof queuePlatformFilter)}
                      className="input-field h-10"
                    >
                      {queuePlatformOptions.map((option) => (
                        <option key={option.id} value={option.id}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="flex gap-2 overflow-x-auto pb-1">
                  {queueStatusOptions.map((option) => (
                    <button
                      key={option.id}
                      onClick={() => setQueueStatusFilter(option.id)}
                      className={`shrink-0 px-3 py-2 rounded-full border text-xs font-bold transition-colors ${
                        queueStatusFilter === option.id
                          ? 'bg-slate-900 text-white border-slate-900'
                          : 'bg-white text-slate-600 border-slate-200'
                      }`}
                    >
                      {option.label} · {queueCounters[option.id]}
                    </button>
                  ))}
                </div>
              </div>
              <div className="tg-card">
                <div className="p-4 border-b flex items-center justify-between">
                  <h3 className="text-[15px] font-bold uppercase text-[#707579] tracking-tight">Очередь публикаций</h3>
                  <button onClick={() => telegramId && loadTasks(telegramId)} className="text-[#24a1de]"><RefreshCcw size={16} /></button>
                </div>
                <div className="divide-y overflow-auto max-h-[780px]">
                  {tasksLoading && (
                    <>
                      {[1, 2, 3].map((item) => (
                        <div key={item} className="p-4">
                          <div className="animate-pulse flex gap-4">
                            <div className="w-24 aspect-[9/16] rounded-2xl bg-slate-200" />
                            <div className="flex-1 space-y-3">
                              <div className="h-4 w-40 bg-slate-200 rounded" />
                              <div className="h-3 w-28 bg-slate-100 rounded" />
                              <div className="h-10 w-full bg-slate-100 rounded-xl" />
                              <div className="h-9 w-full bg-slate-100 rounded-xl" />
                            </div>
                          </div>
                        </div>
                      ))}
                    </>
                  )}
                  {!tasksLoading && filteredTasks.length === 0 && (
                    <div className="p-8 text-center text-sm text-[#707579]">
                      По текущим фильтрам ничего не найдено. Попробуй сменить платформу, статус или строку поиска.
                    </div>
                  )}
                  {!tasksLoading && filteredTasks.map(task => {
                    const account = task.target_account_id ? accountsById[task.target_account_id] : undefined;
                    const platform = normalizeNetwork(task.target_platform || account?.channel_code || task.type);
                    const platformMeta = getPlatformMeta(platform);
                    const localPreviewUrl = task.output_path && task.status === 'completed' && telegramId
                      ? `${API_BASE}/tasks/${telegramId}/${task.id}/file`
                      : '';
                    const previewUrl = task.preview_url || localPreviewUrl;
                    return (
                      <div key={task.id} className="p-4 space-y-4 relative">
                        <button
                          onClick={() => removeTaskFromQueue(task.id)}
                          disabled={deletingTaskId === task.id}
                          title="Удалить из очереди"
                          aria-label="Удалить из очереди"
                          className="absolute top-3 right-3 z-10 h-8 w-8 rounded-full border border-slate-200 bg-white/85 text-slate-400 inline-flex items-center justify-center backdrop-blur-sm transition-colors hover:text-rose-600 hover:border-rose-200 hover:bg-rose-50 disabled:opacity-50"
                        >
                          {deletingTaskId === task.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                        </button>
                        <div className="flex gap-4 items-start">
                          <div className="w-24 shrink-0">
                            <div className="relative aspect-[9/16] rounded-[22px] overflow-hidden bg-gradient-to-br from-slate-900 via-slate-700 to-slate-500 shadow-sm">
                              {previewUrl ? (
                                isImagePreview(previewUrl) ? (
                                  <img
                                    src={previewUrl}
                                    className="absolute inset-0 w-full h-full object-cover"
                                    alt=""
                                  />
                                ) : (
                                  <video
                                    src={previewUrl}
                                    className="absolute inset-0 w-full h-full object-cover"
                                    muted
                                    playsInline
                                    preload="metadata"
                                  />
                                )
                              ) : (
                                <div className="absolute inset-0 flex flex-col items-center justify-center text-white/90 gap-2">
                                  {platformMeta.icon}
                                  <span className="text-[10px] font-bold uppercase tracking-[0.18em]">{platformMeta.label}</span>
                                </div>
                              )}
                              <div className="absolute top-2 left-2">
                                <span className={`inline-flex items-center gap-1 text-[10px] font-bold px-2 py-1 rounded-full border backdrop-blur-sm bg-white/90 ${platformMeta.tone}`}>
                                  {platformMeta.icon}
                                  {platformMeta.label}
                                </span>
                              </div>
                            </div>
                          </div>
                          <div className="flex-1 min-w-0 space-y-3">
                            <div className="flex flex-wrap items-start justify-between gap-3">
                              <div className="min-w-0">
                                <p className="text-[15px] font-semibold text-slate-900 truncate">{getTaskDisplayTitle(task)}</p>
                                <div className="flex flex-wrap gap-x-3 gap-y-1 mt-1 text-[12px] text-[#707579]">
                                  <span>{getTaskSourceHint(task)}</span>
                                  <span>ID #{task.id}</span>
                                  <span>{account?.account_name || 'Локальная очередь'}</span>
                                </div>
                              </div>
                              <div className="flex flex-wrap gap-2">
                                <span className={`inline-flex items-center gap-1 text-[11px] font-bold px-2.5 py-1 rounded-full border ${getProcessingTone(task.status)}`}>
                                  {task.status === 'processing' ? <Loader2 size={13} className="animate-spin" /> : task.status === 'completed' ? <CheckCircle2 size={13} /> : task.status === 'failed' ? <AlertTriangle size={13} /> : <Clock3 size={13} />}
                                  {getProcessingLabel(task.status)}
                                </span>
                                <span className={`inline-flex items-center gap-1 text-[11px] font-bold px-2.5 py-1 rounded-full border ${getPublicationTone(task.publishing_status)}`}>
                                  {task.publishing_status === 'published' ? <CheckCircle2 size={13} /> : task.publishing_status === 'failed' ? <AlertTriangle size={13} /> : task.publishing_status === 'in_progress' ? <Loader2 size={13} className="animate-spin" /> : <CalendarDays size={13} />}
                                  {getStatusLabel(task.publishing_status)}
                                </span>
                              </div>
                            </div>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[12px] text-slate-600">
                              <div className="rounded-xl bg-slate-50 border border-slate-200 px-3 py-2">
                                <p className="text-[11px] uppercase tracking-wide text-[#8b93a1]">Создано</p>
                                <p className="mt-1 font-medium text-slate-900">{formatDateTimeLabel(task.created_at)}</p>
                              </div>
                              <div className="rounded-xl bg-slate-50 border border-slate-200 px-3 py-2">
                                <p className="text-[11px] uppercase tracking-wide text-[#8b93a1]">Публикация</p>
                                <p className="mt-1 font-medium text-slate-900">{formatDateTimeLabel(task.publish_at)}</p>
                              </div>
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_auto_auto] gap-2">
                              <input
                                type="datetime-local"
                                value={scheduleInputs[task.id] || ''}
                                onChange={(e) => setScheduleInputs(prev => ({ ...prev, [task.id]: e.target.value }))}
                                className="input-field text-xs h-10 py-1"
                              />
                              <button
                                onClick={() => saveTaskSchedule(task.id)}
                                disabled={activeTaskId === task.id}
                                className="h-10 px-4 bg-blue-50 text-[#24a1de] text-xs font-bold rounded-xl disabled:opacity-50"
                              >
                                {activeTaskId === task.id ? '...' : 'Обновить дату'}
                              </button>
                              {task.output_path && task.status === 'completed' ? (
                                <a
                                  href={previewUrl}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="h-10 px-4 bg-emerald-50 text-emerald-700 text-xs font-bold rounded-xl inline-flex items-center justify-center gap-2"
                                >
                                  <Download size={14} />
                                  Скачать
                                </a>
                              ) : (
                                <div className="h-10 px-4 bg-slate-100 text-slate-400 text-xs font-bold rounded-xl inline-flex items-center justify-center">
                                  Нет файла
                                </div>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </main>
      <nav className="bottom-nav">
        {[
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
