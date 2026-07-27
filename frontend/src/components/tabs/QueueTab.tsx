import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { 
  Video, CalendarDays, Clock3,
  Loader2, Download, Trash2, Globe2, ExternalLink, X
} from 'lucide-react';
import { apiClient } from '../../api/client';
import { usePostMyPostProject } from '../../context/PostMyPostProjectContext';
import { useTelegram } from '../../context/TelegramContext';
import { VideoTaskItem } from '../../types';

const toLocalInput = (isoValue?: string | null): string => {
  if (!isoValue) return '';
  const date = new Date(isoValue);
  if (Number.isNaN(date.getTime())) return '';
  const localDate = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return localDate.toISOString().slice(0, 16);
};

const dateToPeriodStartIso = (value: string): string | undefined => {
  if (!value) return undefined;
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return undefined;
  return date.toISOString();
};

const dateToPeriodEndIso = (value: string): string | undefined => {
  if (!value) return undefined;
  const date = new Date(`${value}T23:59:59.999`);
  if (Number.isNaN(date.getTime())) return undefined;
  return date.toISOString();
};

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

const resolvePreviewUrl = (value: string | null | undefined, apiBase: string) => {
  const raw = String(value || '').trim();
  if (!raw) return undefined;
  if (raw.startsWith('/media/')) return `${apiBase}${raw}`;
  const mediaParts = raw.split('/media/');
  if (mediaParts.length > 1) return `${apiBase}/media/${mediaParts[1]}`;
  return raw;
};

const isImagePreview = (value: string | undefined) =>
  Boolean(value && /\.(png|jpe?g|webp)(?:$|\?)/i.test(value));

export const QueueTab: React.FC = () => {
  const { telegramId } = useTelegram();
  const { selectedProjectId } = usePostMyPostProject();
  const [tasks, setTasks] = useState<VideoTaskItem[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [queueStatusFilter, setQueueStatusFilter] = useState<'all' | 'active' | 'scheduled' | 'published' | 'failed'>('all');
  const [queuePlatformFilter, setQueuePlatformFilter] = useState<'all' | 'instagram' | 'youtube' | 'tiktok' | 'other'>('all');
  const [queueSearch, setQueueSearch] = useState('');
  const [publishDateFrom, setPublishDateFrom] = useState('');
  const [publishDateTo, setPublishDateTo] = useState('');
  
  const [scheduleInputs, setScheduleInputs] = useState<Record<number, string>>({});
  const [activeTaskId, setActiveTaskId] = useState<number | null>(null);
  const [deletingTaskId, setDeletingTaskId] = useState<number | null>(null);
  const [publishingTaskId, setPublishingTaskId] = useState<number | null>(null);
  
  const loadTasks = async () => {
    if (!telegramId) return;
    setTasksLoading(true);
    try {
      const data = await apiClient.getTasks(telegramId, {
        publish_from: dateToPeriodStartIso(publishDateFrom),
        publish_to: dateToPeriodEndIso(publishDateTo || publishDateFrom),
        project_id: selectedProjectId,
      });
      setTasks(data);
      setScheduleInputs(
        data.reduce<Record<number, string>>((acc, task) => {
          if (task.type === 'avatar_youtube') return acc;
          acc[task.id] = toLocalInput(task.publish_at);
          return acc;
        }, {})
      );
    } catch (error) {
      console.error(error);
    } finally {
      setTasksLoading(false);
    }
  };

  useEffect(() => {
    loadTasks();
    const interval = setInterval(loadTasks, 15000);
    return () => clearInterval(interval);
  }, [telegramId, selectedProjectId, publishDateFrom, publishDateTo]);

  const saveTaskSchedule = async (taskId: number, overrideValue?: string | null) => {
    if (!telegramId) return;
    const localValue = overrideValue === undefined ? scheduleInputs[taskId] : overrideValue;
    const publishAt = localValue ? new Date(localValue) : null;
    setActiveTaskId(taskId);
    try {
      await apiClient.updateTaskSchedule(telegramId, taskId, publishAt ? publishAt.toISOString() : null);
      await loadTasks();
    } catch (error) {
    } finally {
      setActiveTaskId(null);
    }
  };

  const publishTaskNow = async (taskId: number) => {
    if (!telegramId) return;
    setPublishingTaskId(taskId);
    try {
      await apiClient.publishTaskNow(telegramId, taskId);
      await loadTasks();
    } catch (error) {
    } finally {
      setPublishingTaskId(null);
    }
  };

  const deleteTask = async (taskId: number) => {
    if (!telegramId) return;
    if (!window.confirm('Точно удалить задачу?')) return;
    setDeletingTaskId(taskId);
    try {
      await apiClient.deleteTask(telegramId, taskId);
      await loadTasks();
    } catch (error) {
    } finally {
      setDeletingTaskId(null);
    }
  };

  const filteredTasks = tasks.filter(task => {
    if (task.type === 'avatar_youtube') return false;
    if (queueStatusFilter !== 'all') {
      if (queueStatusFilter === 'active' && !['pending', 'processing'].includes(task.status)) return false;
      if (queueStatusFilter === 'scheduled' && task.publishing_status !== 'scheduled') return false;
      if (queueStatusFilter === 'published' && task.publishing_status !== 'published') return false;
      if (queueStatusFilter === 'failed' && (task.status === 'failed' || task.publishing_status === 'failed')) return false;
    }
    if (queuePlatformFilter !== 'all') {
      const target = (task.target_platform || '').toLowerCase();
      if (queuePlatformFilter === 'other' && ['instagram', 'youtube', 'tiktok'].includes(target)) return false;
      if (queuePlatformFilter !== 'other' && target !== queuePlatformFilter) return false;
    }
    if (queueSearch) {
      const s = queueSearch.toLowerCase();
      const title = (task.source_title || '').toLowerCase();
      const url = (task.source_url || '').toLowerCase();
      if (!title.includes(s) && !url.includes(s)) return false;
    }
    return true;
  });
  const scheduledInPeriodCount = filteredTasks.filter(task => task.publishing_status === 'scheduled' && task.publish_at).length;
  const periodFilterEnabled = Boolean(publishDateFrom || publishDateTo);

  return (
    <motion.div key="queue" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-4 pb-20">
      <div className="tg-card p-3">
        <div className="flex flex-col gap-3">
          <input
            type="text"
            placeholder="Поиск по названию или ссылке..."
            value={queueSearch}
            onChange={(e) => setQueueSearch(e.target.value)}
            className="input-field h-10 w-full"
          />
          <div className="flex gap-2 overflow-x-auto pb-1 hide-scrollbar">
            <select
              value={queueStatusFilter}
              onChange={(e) => setQueueStatusFilter(e.target.value as any)}
              className="input-field h-9 text-xs min-w-[120px]"
            >
              <option value="all">Все статусы</option>
              <option value="active">В работе</option>
              <option value="scheduled">Запланированы</option>
              <option value="published">Опубликованы</option>
              <option value="failed">Ошибки</option>
            </select>
            <select
              value={queuePlatformFilter}
              onChange={(e) => setQueuePlatformFilter(e.target.value as any)}
              className="input-field h-9 text-xs min-w-[130px]"
            >
              <option value="all">Платформы</option>
              <option value="instagram">Instagram</option>
              <option value="youtube">YouTube</option>
              <option value="tiktok">TikTok</option>
              <option value="other">Прочие</option>
            </select>
          </div>
          <div className="grid grid-cols-[1fr_1fr_auto] gap-2 items-end">
            <div>
              <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1 block">
                Публикации с
              </label>
              <input
                type="date"
                value={publishDateFrom}
                onChange={(e) => setPublishDateFrom(e.target.value)}
                className="input-field h-9 text-xs w-full"
              />
            </div>
            <div>
              <label className="text-[10px] font-bold text-slate-500 uppercase tracking-wider mb-1 block">
                По
              </label>
              <input
                type="date"
                value={publishDateTo}
                onChange={(e) => setPublishDateTo(e.target.value)}
                className="input-field h-9 text-xs w-full"
              />
            </div>
            <button
              onClick={() => {
                setPublishDateFrom('');
                setPublishDateTo('');
              }}
              disabled={!periodFilterEnabled}
              className="h-9 w-9 bg-slate-100 text-slate-500 rounded-xl inline-flex items-center justify-center disabled:opacity-50"
              title="Сбросить период"
            >
              <X size={14} />
            </button>
          </div>
          {periodFilterEnabled && (
            <div className="px-3 py-2 rounded-xl bg-amber-50 border border-amber-100 text-[11px] font-semibold text-amber-700 flex items-center justify-between gap-3">
              <span>Запланировано за период</span>
              <span className="text-sm font-black">{scheduledInPeriodCount}</span>
            </div>
          )}
        </div>
      </div>

      <div className="space-y-3">
        {tasksLoading && tasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 gap-3 text-slate-400">
            <Loader2 className="animate-spin w-8 h-8" />
            <p className="text-sm font-medium">Загрузка задач...</p>
          </div>
        ) : filteredTasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 px-6 text-center bg-white rounded-2xl border border-slate-100 shadow-sm">
            <div className="w-16 h-16 bg-slate-50 rounded-full flex items-center justify-center mb-4">
              <CalendarDays className="w-8 h-8 text-slate-300" />
            </div>
            <h3 className="text-[17px] font-bold text-slate-800 mb-1">Нет задач</h3>
            <p className="text-sm text-slate-500">
              {tasks.length === 0 ? 'Вы еще не добавили ни одного видео в очередь.' : 'По вашему запросу ничего не найдено.'}
            </p>
          </div>
        ) : (
          filteredTasks.map(task => {
            const isProcessing = task.status === 'pending' || task.status === 'processing';
            const isCompleted = task.status === 'completed';
            const isError = task.status === 'failed' || task.publishing_status === 'failed';
            const isPublished = task.publishing_status === 'published';
            const isScheduled = task.publishing_status === 'scheduled';
            const API_BASE = import.meta.env.VITE_API_BASE || '/api';
            const filePreviewUrl = task.output_path ? `${API_BASE}/tasks/${telegramId}/${task.id}/file` : undefined;
            const fileDownloadUrl = task.output_path ? `${API_BASE}/tasks/${telegramId}/${task.id}/file?download=1` : undefined;
            const postPreviewUrl = resolvePreviewUrl(task.preview_url, API_BASE);
            const postPreviewIsImage = isImagePreview(postPreviewUrl);

            return (
              <div key={task.id} className={`tg-card overflow-hidden transition-all ${isPublished ? 'opacity-75' : ''}`}>
                {filePreviewUrl ? (
                  <div className="relative bg-black aspect-video overflow-hidden">
                    <video
                      src={filePreviewUrl}
                      className="w-full h-full object-contain bg-black"
                      controls
                      preload="metadata"
                    />
                    {postPreviewUrl && (
                      <a
                        href={postPreviewUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="absolute top-2 right-2 h-8 px-3 rounded-lg bg-white/90 text-slate-900 text-[11px] font-bold inline-flex items-center gap-1 shadow-sm"
                      >
                        <ExternalLink size={13} />
                        PostMyPost
                      </a>
                    )}
                  </div>
                ) : postPreviewUrl && postPreviewIsImage ? (
                  <a
                    href={postPreviewUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="block relative bg-black aspect-video overflow-hidden"
                  >
                    <img
                      src={postPreviewUrl}
                      alt=""
                      className="w-full h-full object-contain bg-black"
                      loading="lazy"
                    />
                  </a>
                ) : postPreviewUrl ? (
                  <a
                    href={postPreviewUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="h-14 px-4 bg-slate-900 text-white text-xs font-bold flex items-center justify-between gap-3"
                  >
                    <span className="inline-flex items-center gap-2">
                      <ExternalLink size={15} />
                      Открыть превью PostMyPost
                    </span>
                    <span className="text-white/50 truncate max-w-[140px]">{postPreviewUrl}</span>
                  </a>
                ) : null}
                <div className="p-4">
                  <div className="flex justify-between items-start gap-4 mb-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className="px-2 py-0.5 bg-slate-100 text-slate-600 rounded-full text-[10px] font-bold uppercase tracking-wide">
                          ID: {task.id}
                        </span>
                        <span className="px-2 py-0.5 bg-blue-50 text-blue-600 rounded-full text-[10px] font-bold uppercase tracking-wide">
                          {task.type}
                        </span>
                        {task.target_platform && (
                          <span className="px-2 py-0.5 bg-indigo-50 text-indigo-600 rounded-full text-[10px] font-bold uppercase tracking-wide">
                            {task.target_platform}
                          </span>
                        )}
                      </div>
                      <h4 className="text-[15px] font-bold text-slate-900 leading-snug truncate">
                        {task.source_title || cleanTaskSource(task.source_url) || 'Без названия'}
                      </h4>
                      {task.target_account_id && (
                        <p className="text-[11px] text-slate-500 mt-1 flex items-center gap-1">
                          <span className="w-1.5 h-1.5 rounded-full bg-slate-300"></span>
                          Аккаунт ID: {task.target_account_id}
                        </p>
                      )}
                    </div>
                    <button
                      onClick={() => deleteTask(task.id)}
                      disabled={deletingTaskId === task.id}
                      className="p-2 text-slate-400 hover:text-rose-500 hover:bg-rose-50 rounded-lg transition-colors"
                    >
                      {deletingTaskId === task.id ? <Loader2 size={18} className="animate-spin" /> : <Trash2 size={18} />}
                    </button>
                  </div>

                  <div className="grid grid-cols-2 gap-2 mb-4">
                    <div className={`p-2.5 rounded-xl border flex flex-col gap-1 ${
                      isProcessing ? 'bg-blue-50/50 border-blue-100' :
                      isCompleted ? 'bg-emerald-50/50 border-emerald-100' :
                      isError ? 'bg-rose-50/50 border-rose-100' : 'bg-slate-50 border-slate-100'
                    }`}>
                      <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1">
                        <Video size={12} /> Обработка
                      </span>
                      <span className={`text-[13px] font-bold ${
                        isProcessing ? 'text-blue-600' :
                        isCompleted ? 'text-emerald-600' :
                        isError ? 'text-rose-600' : 'text-slate-700'
                      }`}>
                        {task.status === 'pending' ? 'В очереди' :
                         task.status === 'processing' ? 'Монтаж...' :
                         task.status === 'completed' ? 'Готово' : 'Ошибка'}
                      </span>
                    </div>

                    <div className={`p-2.5 rounded-xl border flex flex-col gap-1 ${
                      isPublished ? 'bg-indigo-50/50 border-indigo-100' :
                      isScheduled ? 'bg-amber-50/50 border-amber-100' :
                      task.publishing_status === 'failed' ? 'bg-rose-50/50 border-rose-100' :
                      'bg-slate-50 border-slate-100'
                    }`}>
                      <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1">
                        <Globe2 size={12} /> Публикация
                      </span>
                      <span className={`text-[13px] font-bold ${
                        isPublished ? 'text-indigo-600' :
                        isScheduled ? 'text-amber-600' :
                        task.publishing_status === 'failed' ? 'text-rose-600' :
                        'text-slate-700'
                      }`}>
                        {task.publishing_status === 'published' ? 'Опубликовано' :
                         task.publishing_status === 'scheduled' ? 'Запланировано' :
                         task.publishing_status === 'in_progress' ? 'Публикуем...' :
                         task.publishing_status === 'failed' ? 'Ошибка' : 'Не назначено'}
                      </span>
                    </div>
                  </div>

                  <div className="bg-slate-50 rounded-xl p-3 border border-slate-100 space-y-3">
                    <div className="flex items-center gap-2">
                      <Clock3 size={14} className="text-[#24a1de]" />
                      <span className="text-xs font-semibold text-slate-700">Дата и время публикации</span>
                    </div>
                    
                    <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto_auto_auto_auto] gap-2">
                      <input
                        type="datetime-local"
                        value={scheduleInputs[task.id] || ''}
                        onChange={(e) => setScheduleInputs(prev => ({ ...prev, [task.id]: e.target.value }))}
                        className="input-field text-xs h-10 py-1 w-full"
                      />
                      <button
                        onClick={() => saveTaskSchedule(task.id)}
                        disabled={activeTaskId === task.id}
                        className="h-10 px-4 bg-blue-50 text-[#24a1de] text-xs font-bold rounded-xl disabled:opacity-50"
                      >
                        {activeTaskId === task.id ? '...' : 'Обновить дату'}
                      </button>
                      <button
                        onClick={() => {
                          setScheduleInputs(prev => ({ ...prev, [task.id]: '' }));
                          void saveTaskSchedule(task.id, null);
                        }}
                        disabled={activeTaskId === task.id || !scheduleInputs[task.id]}
                        className="h-10 px-4 sm:px-0 sm:w-10 bg-slate-100 text-slate-500 text-xs font-bold rounded-xl inline-flex items-center justify-center disabled:opacity-50"
                        title="Очистить дату"
                      >
                        <X size={14} />
                      </button>
                      {task.status === 'completed' && task.publishing_status !== 'published' && (
                        <button
                          onClick={() => publishTaskNow(task.id)}
                          disabled={publishingTaskId === task.id || task.publishing_status === 'in_progress'}
                          className="h-10 px-4 bg-sky-50 text-sky-700 text-xs font-bold rounded-xl disabled:opacity-50"
                        >
                          {publishingTaskId === task.id ? '...' : 'Опубликовать'}
                        </button>
                      )}
                      {task.output_path && task.status === 'completed' ? (
                        <a
                          href={fileDownloadUrl}
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
          })
        )}
      </div>
    </motion.div>
  );
};
