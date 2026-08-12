import React, { useEffect, useRef, useState } from 'react';
import { Film, Loader2, Trash2, Upload } from 'lucide-react';
import { apiClient } from '../../../api/client';
import { getApiErrorMessage } from '../../../api/errors';
import { BrollAsset } from '../../../types';

type ProjectBrollLibraryProps = {
  telegramId: string | null;
  projectId: number | null;
};

export const ProjectBrollLibrary: React.FC<ProjectBrollLibraryProps> = ({ telegramId, projectId }) => {
  const [assets, setAssets] = useState<BrollAsset[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [error, setError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const loadAssets = async () => {
    if (!telegramId || !projectId) {
      setAssets([]);
      return;
    }
    setLoading(true);
    setError('');
    try {
      setAssets(await apiClient.getBrollAssets(telegramId, projectId));
    } catch (err) {
      setError(getApiErrorMessage(err, 'Не удалось загрузить библиотеку B-roll'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAssets();
  }, [telegramId, projectId]);

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    if (!telegramId || !projectId || files.length === 0) return;
    setUploading(true);
    setError('');
    try {
      const uploaded = await apiClient.uploadBroll(telegramId, files, projectId);
      setAssets(current => [...uploaded, ...current]);
    } catch (err) {
      setError(getApiErrorMessage(err, 'Не удалось загрузить B-roll'));
    } finally {
      setUploading(false);
      event.target.value = '';
    }
  };

  const handleDelete = async (asset: BrollAsset) => {
    if (!telegramId || !projectId || !window.confirm(`Удалить «${asset.original_filename}»?`)) return;
    setDeletingId(asset.id);
    try {
      await apiClient.deleteBroll(telegramId, asset.id, projectId);
      setAssets(current => current.filter(item => item.id !== asset.id));
    } catch (err) {
      setError(getApiErrorMessage(err, 'Не удалось удалить B-roll'));
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <section className="rounded-2xl border border-slate-100 bg-white p-4 shadow-sm space-y-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-bold text-slate-800">
            <Film size={16} className="text-[#24a1de]" />
            B-roll проекта
          </h3>
          <p className="mt-1 text-xs text-slate-500">Случайные фрагменты для уникализации роликов Vizard.</p>
        </div>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={!projectId || loading || uploading}
          className="inline-flex h-9 items-center gap-2 rounded-xl bg-[#24a1de] px-3 text-xs font-bold text-white disabled:opacity-50"
        >
          {uploading ? <Loader2 size={14} className="animate-spin" /> : <Upload size={14} />}
          Загрузить
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept="video/*,.m4v"
          className="hidden"
          onChange={handleUpload}
        />
      </div>

      {error && <p className="rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-600">{error}</p>}
      {loading ? (
        <div className="flex items-center gap-2 py-4 text-xs text-slate-400">
          <Loader2 size={15} className="animate-spin" /> Загружаю библиотеку…
        </div>
      ) : assets.length === 0 ? (
        <p className="py-3 text-xs text-slate-400">В этом проекте пока нет B-roll.</p>
      ) : (
        <div className="space-y-2">
          {assets.map(asset => (
            <div key={asset.id} className="flex items-center justify-between gap-3 rounded-xl bg-slate-50 px-3 py-2">
              <span className="min-w-0 truncate text-xs font-medium text-slate-700">{asset.original_filename}</span>
              <button
                type="button"
                onClick={() => handleDelete(asset)}
                disabled={deletingId === asset.id}
                aria-label={`Удалить ${asset.original_filename}`}
                className="shrink-0 rounded-lg p-2 text-slate-400 hover:bg-rose-50 hover:text-rose-600 disabled:opacity-50"
              >
                {deletingId === asset.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
};
