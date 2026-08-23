import React, { useEffect, useState } from 'react';
import { Loader2, Plus, RefreshCw, Trash2 } from 'lucide-react';
import { apiClient } from '../../../api/client';
import { ReferenceChannel } from '../../../types';

type Props = { telegramId: string | null; projectId: number | null };

export const ReferenceChannelLibrary: React.FC<Props> = ({ telegramId, projectId }) => {
  const [items, setItems] = useState<ReferenceChannel[]>([]);
  const [platform, setPlatform] = useState('youtube');
  const [sourceUrl, setSourceUrl] = useState('');
  const [title, setTitle] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    if (!telegramId || !projectId) return;
    setLoading(true);
    try {
      setItems(await apiClient.getReferenceChannels(telegramId, projectId));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [telegramId, projectId]);

  const add = async () => {
    if (!telegramId || !projectId || !sourceUrl.trim()) return;
    setSaving(true);
    try {
      await apiClient.addReferenceChannel(telegramId, {
        project_id: projectId,
        platform,
        source_url: sourceUrl.trim(),
        title: title.trim() || undefined,
      });
      setSourceUrl('');
      setTitle('');
      await load();
    } catch (error: any) {
      alert(error.response?.data?.detail || 'Не удалось добавить источник');
    } finally {
      setSaving(false);
    }
  };

  const sync = async () => {
    if (!telegramId || !projectId) return;
    setSaving(true);
    try {
      await apiClient.syncReferenceChannels(telegramId, projectId);
      alert('Синхронизация поставлена в очередь');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="tg-card p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h3 className="text-[15px] font-bold text-slate-900">Библиотека референсных каналов</h3>
          <p className="text-[11px] text-slate-500 mt-1">Каждый день парсер возьмёт до трёх свежих сильных публикаций.</p>
        </div>
        <button onClick={sync} disabled={saving || loading} className="h-9 px-3 rounded-xl bg-slate-100 text-slate-700 text-xs font-bold flex items-center gap-1">
          <RefreshCw size={14} /> Сейчас
        </button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-[110px_1fr_160px_auto] gap-2">
        <select value={platform} onChange={event => setPlatform(event.target.value)} className="input-field h-10 text-sm">
          <option value="youtube">YouTube</option>
          <option value="instagram">Instagram</option>
          <option value="tiktok">TikTok-ссылка</option>
        </select>
        <input value={sourceUrl} onChange={event => setSourceUrl(event.target.value)} placeholder="Ссылка на канал или пост" className="input-field h-10 text-sm" />
        <input value={title} onChange={event => setTitle(event.target.value)} placeholder="Название" className="input-field h-10 text-sm" />
        <button onClick={add} disabled={saving || !sourceUrl.trim()} className="h-10 px-3 rounded-xl bg-[#24a1de] text-white text-xs font-bold flex items-center justify-center gap-1 disabled:opacity-50">
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />} Добавить
        </button>
      </div>
      {loading ? <Loader2 size={18} className="animate-spin text-slate-400" /> : items.map(item => (
        <div key={item.id} className="flex items-center justify-between gap-3 rounded-xl bg-slate-50 px-3 py-2 text-xs">
          <div className="min-w-0"><b>{item.title || item.platform}</b><div className="truncate text-slate-500">{item.source_url}</div></div>
          <button onClick={async () => { await apiClient.deleteReferenceChannel(telegramId!, item.id); await load(); }} className="text-rose-500"><Trash2 size={15} /></button>
        </div>
      ))}
    </div>
  );
};
