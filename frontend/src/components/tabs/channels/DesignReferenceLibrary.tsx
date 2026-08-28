import React, { useEffect, useRef, useState } from 'react';
import { ImagePlus, Loader2, Trash2 } from 'lucide-react';
import { apiClient } from '../../../api/client';
import { DesignReference } from '../../../types';

type Props = { telegramId: string; projectId: number };

export const DesignReferenceLibrary: React.FC<Props> = ({ telegramId, projectId }) => {
  const [format, setFormat] = useState<'carousel' | 'story'>('carousel');
  const [items, setItems] = useState<DesignReference[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const API_BASE = import.meta.env.VITE_API_BASE || '/api';

  const mediaUrl = (path: string) => {
    if (path.startsWith('http://') || path.startsWith('https://')) return path;
    return `${API_BASE}/media/${path.split('/media/')[1] || ''}`;
  };
  const load = async () => {
    setLoading(true);
    try { setItems(await apiClient.getDesignReferences(telegramId, projectId, format)); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [telegramId, projectId, format]);

  const upload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try { await apiClient.uploadDesignReference(telegramId, projectId, format, file); await load(); }
    catch (error: any) { alert(error.response?.data?.detail || 'Не удалось загрузить дизайн-референс'); }
    finally { setUploading(false); event.target.value = ''; }
  };

  return (
    <div className="tg-card p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h3 className="text-[15px] font-bold text-slate-900">Дизайн-референсы</h3>
          <p className="text-[11px] text-slate-500 mt-1">Система нормализует каждый референс под точный размер формата.</p>
        </div>
        <select value={format} onChange={event => setFormat(event.target.value as 'carousel' | 'story')} className="input-field h-9 text-xs w-32">
          <option value="carousel">Карусель 4:5</option>
          <option value="story">Stories 9:16</option>
        </select>
      </div>
      <input ref={inputRef} type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={upload} />
      <button onClick={() => inputRef.current?.click()} disabled={uploading} className="h-9 px-3 rounded-xl bg-[#24a1de] text-white text-xs font-bold flex items-center gap-1 disabled:opacity-50">
        {uploading ? <Loader2 size={14} className="animate-spin" /> : <ImagePlus size={14} />} Добавить референс
      </button>
      {loading ? <Loader2 size={18} className="animate-spin text-slate-400" /> : (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {items.map(item => (
            <div key={item.id} className="relative rounded-lg overflow-hidden border border-slate-200 bg-white">
              <img src={mediaUrl(item.file_path)} alt="Design reference" className="w-full aspect-[4/5] object-cover" />
              <button onClick={async () => { await apiClient.deleteDesignReference(telegramId, item.id); await load(); }} className="absolute top-1 right-1 h-6 w-6 rounded-md bg-black/70 text-white flex items-center justify-center"><Trash2 size={12} /></button>
              <div className="text-[10px] text-slate-500 p-1 text-center">{item.width}×{item.height}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
