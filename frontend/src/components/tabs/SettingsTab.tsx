import React, { useState, useEffect, useRef } from 'react';
import { motion } from 'framer-motion';
import { Settings, Save, Loader2, Link2, BookOpen, User, Mic, Upload, Image as ImageIcon, Trash2, Film } from 'lucide-react';
import { apiClient } from '../../api/client';
import { useTelegram } from '../../context/TelegramContext';
import { ThumbnailReference, ThumbnailFaceReference, AvatarInsertClip } from '../../types';

type VoiceSpeed = {
  chars_per_second?: number;
  demo_char_count?: number;
  demo_duration_seconds?: number;
};

type ElevenLabsVoice = {
  id: string;
  name: string;
  speed?: VoiceSpeed | null;
};

export const SettingsTab: React.FC = () => {
  const { telegramId } = useTelegram();
  const [styleProfile, setStyleProfile] = useState('');
  const [trainingSource, setTrainingSource] = useState('');
  const [videoCount, setVideoCount] = useState('5');
  const [trainingStatus, setTrainingStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [loadingStyle, setLoadingStyle] = useState(false);
  
  const [clonedVoices, setClonedVoices] = useState<ElevenLabsVoice[]>([]);
  const [loadingVoices, setLoadingVoices] = useState(false);
  const [heygenAvatars, setHeygenAvatars] = useState<{id: string, name: string, preview: string}[]>([]);
  const [loadingAvatars, setLoadingAvatars] = useState(false);
  const [selectedAvatar, setSelectedAvatar] = useState<string>('');
  const [selectedVerticalAvatar, setSelectedVerticalAvatar] = useState<string>('');
  const [selectedVoice, setSelectedVoice] = useState<string>('');
  const [savingSettings, setSavingSettings] = useState(false);
  const [savedSettings, setSavedSettings] = useState(false);
  const [thumbnailReferences, setThumbnailReferences] = useState<ThumbnailReference[]>([]);
  const [thumbnailFaceReferences, setThumbnailFaceReferences] = useState<ThumbnailFaceReference[]>([]);
  const [thumbnailFacePath, setThumbnailFacePath] = useState<string>('');
  const [verticalThumbnailFacePath, setVerticalThumbnailFacePath] = useState<string>('');
  const [loadingThumbnailAssets, setLoadingThumbnailAssets] = useState(false);
  const [uploadingThumbnailRef, setUploadingThumbnailRef] = useState(false);
  const [uploadingThumbnailFace, setUploadingThumbnailFace] = useState(false);
  const [deletingThumbnailRefId, setDeletingThumbnailRefId] = useState<number | null>(null);
  const [deletingThumbnailFace, setDeletingThumbnailFace] = useState(false);
  const thumbnailRefInputRef = useRef<HTMLInputElement>(null);
  const thumbnailFaceInputRef = useRef<HTMLInputElement>(null);
  const [avatarInsertClips, setAvatarInsertClips] = useState<AvatarInsertClip[]>([]);
  const [loadingAvatarInsertClips, setLoadingAvatarInsertClips] = useState(false);
  const [uploadingAvatarInsertClip, setUploadingAvatarInsertClip] = useState(false);
  const [deletingAvatarInsertClipId, setDeletingAvatarInsertClipId] = useState<number | null>(null);
  const avatarInsertInputRef = useRef<HTMLInputElement>(null);
  const [avatarInsertStartPercent, setAvatarInsertStartPercent] = useState<number>(50);
  const [avatarInsertEndPercent, setAvatarInsertEndPercent] = useState<number>(95);
  const [avatarInsertClipsCount, setAvatarInsertClipsCount] = useState<number>(2);
  const [reelsBrollCoveragePercent, setReelsBrollCoveragePercent] = useState<number>(50);
  const [youtubeDescriptionTemplate, setYoutubeDescriptionTemplate] = useState<string>('');
  const [avatarScriptDurationMinutes, setAvatarScriptDurationMinutes] = useState<number>(5);

  useEffect(() => {
    const loadStyle = async () => {
      if (!telegramId) return;
      setLoadingStyle(true);
      try {
        const data = await apiClient.getStyleSettings(telegramId);
        setStyleProfile(data.author_style_profile || '');
        setTrainingSource(data.training_source || '');
        if (data.heygen_avatar_id) setSelectedAvatar(data.heygen_avatar_id);
        if (data.heygen_vertical_avatar_id) setSelectedVerticalAvatar(data.heygen_vertical_avatar_id);
        if (data.elevenlabs_voice_id) setSelectedVoice(data.elevenlabs_voice_id);
        setThumbnailFacePath(data.thumbnail_face_path || data.vertical_thumbnail_face_path || '');
        setVerticalThumbnailFacePath(data.vertical_thumbnail_face_path || data.thumbnail_face_path || '');
        setAvatarScriptDurationMinutes(data.avatar_script_duration_minutes ?? 5);
        setAvatarInsertStartPercent(data.avatar_insert_start_percent ?? 50);
        setAvatarInsertEndPercent(data.avatar_insert_end_percent ?? 95);
        setAvatarInsertClipsCount(data.avatar_insert_clips_count ?? 2);
        setReelsBrollCoveragePercent(data.reels_broll_coverage_percent ?? 50);
        setYoutubeDescriptionTemplate(data.youtube_description_template || '');
      } catch (error) {
      } finally {
        setLoadingStyle(false);
      }
    };

    const loadThumbnailAssets = async () => {
      if (!telegramId) return;
      setLoadingThumbnailAssets(true);
      try {
        const [refs, faceRefs] = await Promise.all([
          apiClient.listAllThumbnailReferences(telegramId),
          apiClient.listThumbnailFaceReferences(telegramId),
        ]);
        setThumbnailReferences(refs);
        setThumbnailFaceReferences(faceRefs);
      } catch (error) {
        setThumbnailReferences([]);
        setThumbnailFaceReferences([]);
      } finally {
        setLoadingThumbnailAssets(false);
      }
    };

    const loadAvatarInsertClips = async () => {
      if (!telegramId) return;
      setLoadingAvatarInsertClips(true);
      try {
        const items = await apiClient.listAvatarInsertClips(telegramId);
        setAvatarInsertClips(items);
      } catch (error) {
        setAvatarInsertClips([]);
      } finally {
        setLoadingAvatarInsertClips(false);
      }
    };
    
    const loadVoices = async () => {
      if (!telegramId) return;
      setLoadingVoices(true);
      try {
        const response = await apiClient.getElevenLabsVoices(telegramId);
        if (response && response.voices) {
          const fetchedVoices = response.voices.map((v: any) => ({
            id: v.voice_id,
            name: v.name,
            speed: v.voice_speed || null
          }));
          setClonedVoices(fetchedVoices);
          
          // If no voice is selected but we have fetched voices, select the first one
          if (fetchedVoices.length > 0) {
            setSelectedVoice(prev => prev || fetchedVoices[0].id);
          }
        }
      } catch (error) {
        console.error("Failed to load voices:", error);
      } finally {
        setLoadingVoices(false);
      }
    };

    const loadAvatars = async () => {
      if (!telegramId) return;
      setLoadingAvatars(true);
      try {
        const response = await apiClient.getHeyGenAvatars(telegramId);
        // HeyGen API v3 /avatars usually returns { data: { avatars: [...] } } or { data: [...] }
        const avatarsList = response?.data?.avatars || response?.data || [];
        
        if (Array.isArray(avatarsList)) {
          const fetchedAvatars = avatarsList.map((a: any) => ({
            id: a.avatar_id || a.id,
            name: a.avatar_name || a.name,
            preview: a.preview_image_url || a.preview_video_url || ''
          }));
          setHeygenAvatars(fetchedAvatars);
        if (fetchedAvatars.length > 0) {
          setSelectedAvatar(prev => prev || fetchedAvatars[0].id);
          setSelectedVerticalAvatar(prev => prev || fetchedAvatars[0].id);
        }
        }
      } catch (error) {
        console.error("Failed to load avatars:", error);
      } finally {
        setLoadingAvatars(false);
      }
    };

    loadStyle();
    loadVoices();
    loadAvatars();
    loadThumbnailAssets();
    loadAvatarInsertClips();
  }, [telegramId]);

  const trainStyle = async () => {
    if (!telegramId || !trainingSource) return;
    setTrainingStatus('loading');
    try {
      const data = await apiClient.trainStyle(telegramId, trainingSource, parseInt(videoCount) || 5);
      setStyleProfile(data.style_profile);
      setTrainingStatus('success');
      setTimeout(() => setTrainingStatus('idle'), 3000);
    } catch (error) {
      setTrainingStatus('error');
      setTimeout(() => setTrainingStatus('idle'), 3000);
    }
  };

  const handleSaveSettings = async () => {
    if (!telegramId) return;
    if (avatarInsertEndPercent <= avatarInsertStartPercent) {
      alert('Финиш вставок должен быть больше старта.');
      return;
    }
    setSavingSettings(true);
    try {
      await apiClient.updateSettings(telegramId, {
        author_style_profile: styleProfile,
        heygen_avatar_id: selectedAvatar,
        heygen_vertical_avatar_id: selectedVerticalAvatar || selectedAvatar,
        elevenlabs_voice_id: selectedVoice,
        avatar_insert_start_percent: avatarInsertStartPercent,
        avatar_insert_end_percent: avatarInsertEndPercent,
        avatar_insert_clips_count: avatarInsertClipsCount,
        reels_broll_coverage_percent: reelsBrollCoveragePercent,
        avatar_script_duration_minutes: avatarScriptDurationMinutes,
        youtube_description_template: youtubeDescriptionTemplate,
      });
      setSavedSettings(true);
      setTimeout(() => setSavedSettings(false), 2000);
    } catch (error) {
    } finally {
      setSavingSettings(false);
    }
  };

  const getMediaUrl = (path: string) => {
    if (!path) return '';
    const API_BASE = import.meta.env.VITE_API_BASE || '/api';
    const parts = path.split('/media/');
    if (parts.length > 1) return `${API_BASE}/media/${parts[1]}`;
    return '';
  };

  const handleUploadThumbnailReference = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0 || !telegramId) return;
    setUploadingThumbnailRef(true);
    try {
      const created = await apiClient.uploadThumbnailReferences(telegramId, files, 'both');
      setThumbnailReferences(prev => [...created, ...prev]);
    } catch (error) {
      alert('Ошибка загрузки референса');
    } finally {
      setUploadingThumbnailRef(false);
      if (thumbnailRefInputRef.current) thumbnailRefInputRef.current.value = '';
    }
  };

  const handleDeleteThumbnailReference = async (referenceId: number) => {
    if (!telegramId) return;
    setDeletingThumbnailRefId(referenceId);
    try {
      await apiClient.deleteThumbnailReference(telegramId, referenceId);
      setThumbnailReferences(prev => prev.filter(item => item.id !== referenceId));
    } catch (error) {
      alert('Не удалось удалить референс');
    } finally {
      setDeletingThumbnailRefId(null);
    }
  };

  const handleUploadThumbnailFace = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0 || !telegramId) return;
    setUploadingThumbnailFace(true);
    try {
      const created = await apiClient.uploadThumbnailFaces(telegramId, files);
      setThumbnailFaceReferences(prev => [...created, ...prev]);
      const activePath = thumbnailFacePath || verticalThumbnailFacePath || created[0]?.file_path || '';
      setThumbnailFacePath(activePath);
      setVerticalThumbnailFacePath(activePath);
    } catch (error) {
      alert('Ошибка загрузки фото лица');
    } finally {
      setUploadingThumbnailFace(false);
      if (thumbnailFaceInputRef.current) thumbnailFaceInputRef.current.value = '';
    }
  };

  const handleDeleteThumbnailFace = async () => {
    if (!telegramId) return;
    setDeletingThumbnailFace(true);
    try {
      await apiClient.deleteThumbnailFace(telegramId);
      setThumbnailFacePath('');
      setVerticalThumbnailFacePath('');
      setThumbnailFaceReferences([]);
    } catch (error) {
      alert('Не удалось удалить фото лица');
    } finally {
      setDeletingThumbnailFace(false);
    }
  };

  const activateThumbnailFaceReference = async (reference: ThumbnailFaceReference, target: 'horizontal' | 'vertical') => {
    if (!telegramId) return;
    const previousHorizontalPath = thumbnailFacePath;
    const previousVerticalPath = verticalThumbnailFacePath;
    if (target === 'horizontal') {
      setThumbnailFacePath(reference.file_path);
    } else {
      setVerticalThumbnailFacePath(reference.file_path);
    }
    try {
      const updated = await apiClient.activateThumbnailFaceReference(telegramId, reference.id, target);
      if (target === 'horizontal') {
        setThumbnailFacePath(updated.file_path);
      } else {
        setVerticalThumbnailFacePath(updated.file_path);
      }
    } catch (error) {
      setThumbnailFacePath(previousHorizontalPath);
      setVerticalThumbnailFacePath(previousVerticalPath);
      alert('Не удалось выбрать референс лица');
    }
  };

  const handleDeleteThumbnailFaceReference = async (reference: ThumbnailFaceReference) => {
    if (!telegramId) return;
    setDeletingThumbnailFace(true);
    try {
      const result = await apiClient.deleteThumbnailFaceReference(telegramId, reference.id);
      setThumbnailFaceReferences(prev => prev.filter(item => item.id !== reference.id));
      if (reference.file_path === thumbnailFacePath || reference.file_path === verticalThumbnailFacePath) {
        const nextPath = result.active_face_path || '';
        setThumbnailFacePath(nextPath);
        setVerticalThumbnailFacePath(nextPath);
      }
    } catch (error) {
      alert('Не удалось удалить референс лица');
    } finally {
      setDeletingThumbnailFace(false);
    }
  };

  const thumbnailReferenceHasTarget = (kind: string | undefined, target: 'horizontal' | 'vertical') => {
    const normalized = kind || 'horizontal';
    return normalized === 'both' || normalized === target;
  };

  const toggleThumbnailReferenceTarget = async (
    reference: ThumbnailReference,
    target: 'horizontal' | 'vertical'
  ) => {
    if (!telegramId) return;
    const hasHorizontal = thumbnailReferenceHasTarget(reference.kind, 'horizontal');
    const hasVertical = thumbnailReferenceHasTarget(reference.kind, 'vertical');
    const nextHorizontal = target === 'horizontal' ? !hasHorizontal : hasHorizontal;
    const nextVertical = target === 'vertical' ? !hasVertical : hasVertical;
    if (!nextHorizontal && !nextVertical) return;

    const nextKind = nextHorizontal && nextVertical ? 'both' : nextHorizontal ? 'horizontal' : 'vertical';
    setThumbnailReferences(prev => prev.map(item => item.id === reference.id ? { ...item, kind: nextKind } : item));
    try {
      const updated = await apiClient.updateThumbnailReference(telegramId, reference.id, nextKind);
      setThumbnailReferences(prev => prev.map(item => item.id === reference.id ? updated : item));
    } catch (error) {
      setThumbnailReferences(prev => prev.map(item => item.id === reference.id ? reference : item));
      alert('Не удалось обновить назначение референса');
    }
  };

  const clampPercentValue = (value: number) => {
    if (Number.isNaN(value)) return 0;
    return Math.max(0, Math.min(100, Math.round(value)));
  };

  const extractApiErrorMessage = (error: unknown, fallback: string) => {
    const err = error as any;
    const status = err?.response?.status;
    const detail = err?.response?.data?.detail;
    if (status === 413) {
      return `${fallback}: файл слишком большой для загрузки на сервер`;
    }
    if (Array.isArray(detail)) {
      const messages = detail.map((item) => item?.msg).filter(Boolean);
      if (messages.length) return `${fallback}: ${messages.join('; ')}`;
    }
    if (typeof detail === 'string' && detail.trim()) {
      return `${fallback}: ${detail}`;
    }
    if (typeof err?.message === 'string' && err.message.trim()) {
      return `${fallback}: ${err.message}`;
    }
    return fallback;
  };

  const handleUploadAvatarInsertClip = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (!files.length || !telegramId) return;
    const allowedExtensions = new Set(['mp4', 'mov', 'mkv', 'webm', 'm4v']);
    const invalidFiles = files
      .filter((file) => {
        const ext = file.name.split('.').pop()?.toLowerCase() || '';
        return !allowedExtensions.has(ext);
      })
      .map((file) => file.name);
    if (invalidFiles.length > 0) {
      alert(`Неподдерживаемый формат видео: ${invalidFiles.join(', ')}. Разрешены: mp4, mov, mkv, webm, m4v`);
      if (avatarInsertInputRef.current) avatarInsertInputRef.current.value = '';
      return;
    }
    setUploadingAvatarInsertClip(true);
    try {
      const created = await apiClient.uploadAvatarInsertClips(telegramId, files);
      setAvatarInsertClips((prev) => [...created, ...prev]);
    } catch (error) {
      console.error('Avatar insert upload failed:', error);
      alert(extractApiErrorMessage(error, 'Ошибка загрузки видео-вставки'));
    } finally {
      setUploadingAvatarInsertClip(false);
      if (avatarInsertInputRef.current) avatarInsertInputRef.current.value = '';
    }
  };

  const handleDeleteAvatarInsertClip = async (clipId: number) => {
    if (!telegramId) return;
    setDeletingAvatarInsertClipId(clipId);
    try {
      await apiClient.deleteAvatarInsertClip(telegramId, clipId);
      setAvatarInsertClips((prev) => prev.filter((item) => item.id !== clipId));
    } catch (error) {
      alert('Не удалось удалить видео-вставку');
    } finally {
      setDeletingAvatarInsertClipId(null);
    }
  };

  const avatars = [
    { id: 'Wayne_20240711', name: 'Wayne', desc: 'Строгий, деловой', img: 'https://cdn2.heygen.ai/avatar/v3/Wayne_20240711/preview.jpg' },
    { id: 'Joshua_20240711', name: 'Joshua', desc: 'Харизматичный', img: 'https://cdn2.heygen.ai/avatar/v3/Joshua_20240711/preview.jpg' },
    { id: 'Bella_20240711', name: 'Bella', desc: 'Дружелюбная', img: 'https://cdn2.heygen.ai/avatar/v3/Bella_20240711/preview.jpg' }
  ];

  const formatVoiceSpeed = (speed?: VoiceSpeed | null) => {
    const cps = speed?.chars_per_second;
    if (!cps) return 'Скорость ещё не рассчитана';
    return `${cps.toFixed(2)} симв/сек`;
  };

  if (loadingStyle) {
    return (
      <div className="flex flex-col items-center justify-center py-10 gap-3 text-slate-400">
        <Loader2 className="animate-spin w-8 h-8" />
        <p className="text-sm font-medium">Загрузка настроек...</p>
      </div>
    );
  }

  return (
    <motion.div key="style" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-4 pb-20">
      <div className="flex justify-between items-center bg-white p-3 rounded-2xl shadow-sm border border-slate-100 mb-2">
        <div className="flex items-center gap-2 text-slate-700">
          <Settings size={20} className="text-[#24a1de]" />
          <h2 className="font-bold text-[15px]">Основные настройки</h2>
        </div>
        <button
          onClick={handleSaveSettings}
          disabled={savingSettings}
          className={`h-9 px-4 text-xs font-bold rounded-xl flex items-center justify-center gap-2 shadow-sm transition-all ${
            savedSettings ? 'bg-[#34c759] text-white' : 'bg-[#24a1de] text-white'
          } disabled:opacity-50`}
        >
          {savingSettings ? <Loader2 className="animate-spin" size={14} /> : <Save size={14} />}
          {savedSettings ? 'Сохранено' : 'Сохранить'}
        </button>
      </div>

      <input
        ref={thumbnailRefInputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        multiple
        className="hidden"
        onChange={handleUploadThumbnailReference}
      />
      <input
        ref={thumbnailFaceInputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        multiple
        className="hidden"
        onChange={handleUploadThumbnailFace}
      />
      <input
        ref={avatarInsertInputRef}
        type="file"
        accept="video/mp4,video/quicktime,video/webm,video/x-matroska,video/x-m4v"
        multiple
        className="hidden"
        onChange={handleUploadAvatarInsertClip}
      />

      <div className="tg-card p-4">
        <div className="flex items-center gap-2 mb-3">
          <BookOpen size={18} className="text-[#24a1de]" />
          <h3 className="text-[15px] font-bold text-slate-900">YouTube описание (avatar)</h3>
        </div>
        <label className="text-xs font-bold text-[#707579] uppercase tracking-wider mb-2 block">
          Шаблон описания
        </label>
        <textarea
          value={youtubeDescriptionTemplate}
          onChange={(e) => setYoutubeDescriptionTemplate(e.target.value)}
          placeholder="Ваш базовый шаблон описания. Перед ним автоматически добавится CTA из хука видео."
          className="input-field text-xs min-h-[120px] leading-relaxed resize-y bg-slate-50"
        />
        <p className="text-[11px] text-slate-500 mt-2">
          Шаблон сохраняется как есть. Перед шаблоном система добавляет призыв к действию, сформированный из хука ролика.
        </p>
      </div>

      <div className="tg-card p-4">
        <div className="flex items-center gap-2 mb-3">
          <ImageIcon size={18} className="text-[#24a1de]" />
          <h3 className="text-[15px] font-bold text-slate-900">Обложки: лицо и референсы</h3>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-3">
          <div className="p-3 rounded-xl border border-slate-200 bg-slate-50">
            <div className="flex items-center justify-between gap-2 mb-2">
              <p className="text-xs font-bold text-slate-700 uppercase tracking-wider">Референс лица</p>
              <button
                onClick={() => thumbnailFaceInputRef.current?.click()}
                disabled={uploadingThumbnailFace}
                className="h-8 px-3 rounded-lg bg-slate-900 text-white text-xs font-bold flex items-center gap-1 disabled:opacity-50"
              >
                {uploadingThumbnailFace ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />}
                Загрузить
              </button>
            </div>
            {thumbnailFaceReferences.length > 0 ? (
              <div className="grid grid-cols-2 gap-2">
                {thumbnailFaceReferences.map((item) => {
                  const isYoutube = item.file_path === thumbnailFacePath;
                  const isShorts = item.file_path === verticalThumbnailFacePath;
                  return (
                    <div key={item.id} className={`relative rounded-lg overflow-hidden border bg-white ${isYoutube || isShorts ? 'border-slate-900 ring-2 ring-slate-900/10' : 'border-slate-200'}`}>
                      <img src={getMediaUrl(item.file_path)} alt={`Face reference ${item.id}`} className="w-full h-24 object-cover" />
                      <button
                        onClick={() => handleDeleteThumbnailFaceReference(item)}
                        disabled={deletingThumbnailFace}
                        className="absolute top-1 right-1 h-6 w-6 rounded-md bg-black/70 text-white flex items-center justify-center disabled:opacity-50"
                      >
                        {deletingThumbnailFace ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                      </button>
                      <div className="grid grid-cols-2 gap-1 p-1.5">
                        <button
                          onClick={() => activateThumbnailFaceReference(item, 'horizontal')}
                          className={`h-7 rounded-md text-[11px] font-bold ${isYoutube ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600'}`}
                        >
                          YouTube
                        </button>
                        <button
                          onClick={() => activateThumbnailFaceReference(item, 'vertical')}
                          className={`h-7 rounded-md text-[11px] font-bold ${isShorts ? 'bg-[#24a1de] text-white' : 'bg-slate-100 text-slate-600'}`}
                        >
                          Shorts
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="h-44 rounded-lg border border-dashed border-slate-300 bg-white flex items-center justify-center text-xs text-slate-500">
                Фото лица не загружено
              </div>
            )}
          </div>

          <div className="p-3 rounded-xl border border-slate-200 bg-slate-50">
            <div className="flex items-center justify-between gap-2 mb-2">
              <p className="text-xs font-bold text-slate-700 uppercase tracking-wider">Референсы обложек</p>
              <button
                onClick={() => thumbnailRefInputRef.current?.click()}
                disabled={uploadingThumbnailRef}
                className="h-8 px-3 rounded-lg bg-[#24a1de] text-white text-xs font-bold flex items-center gap-1 disabled:opacity-50"
              >
                {uploadingThumbnailRef ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />}
                Добавить
              </button>
            </div>
            {loadingThumbnailAssets ? (
              <div className="h-44 rounded-lg border border-slate-200 bg-white flex items-center justify-center text-slate-400">
                <Loader2 size={16} className="animate-spin" />
              </div>
            ) : thumbnailReferences.length === 0 ? (
              <div className="h-44 rounded-lg border border-dashed border-slate-300 bg-white flex items-center justify-center text-xs text-slate-500">
                Референсы не загружены
              </div>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-2">
                {thumbnailReferences.map((item) => {
                  const isYoutube = thumbnailReferenceHasTarget(item.kind, 'horizontal');
                  const isShorts = thumbnailReferenceHasTarget(item.kind, 'vertical');
                  return (
                    <div key={item.id} className="relative rounded-lg overflow-hidden border border-slate-200 bg-white">
                      <img src={getMediaUrl(item.file_path)} alt={`Reference ${item.id}`} className="w-full h-28 object-cover" />
                      <button
                        onClick={() => handleDeleteThumbnailReference(item.id)}
                        disabled={deletingThumbnailRefId === item.id}
                        className="absolute top-1 right-1 h-6 w-6 rounded-md bg-black/70 text-white flex items-center justify-center disabled:opacity-50"
                      >
                        {deletingThumbnailRefId === item.id ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                      </button>
                      <div className="grid grid-cols-2 gap-1 p-1.5">
                        <button
                          onClick={() => toggleThumbnailReferenceTarget(item, 'horizontal')}
                          className={`h-7 rounded-md text-[11px] font-bold ${isYoutube ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600'}`}
                        >
                          YouTube
                        </button>
                        <button
                          onClick={() => toggleThumbnailReferenceTarget(item, 'vertical')}
                          className={`h-7 rounded-md text-[11px] font-bold ${isShorts ? 'bg-[#24a1de] text-white' : 'bg-slate-100 text-slate-600'}`}
                        >
                          Shorts
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
            <p className="text-[11px] text-slate-500 mt-2">
              Загружайте пачку картинок сразу. Каждую можно использовать для YouTube, Shorts/Reels или в обоих форматах.
            </p>
          </div>
        </div>
      </div>

      <div className="tg-card p-4">
        <div className="flex items-center gap-2 mb-3">
          <Film size={18} className="text-[#24a1de]" />
          <h3 className="text-[15px] font-bold text-slate-900">Видео-вставки для avatar_youtube</h3>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3">
          <div>
            <label className="text-[11px] text-slate-600 font-semibold">Старт вставок (%)</label>
            <input
              type="number"
              min={0}
              max={99}
              value={avatarInsertStartPercent}
              onChange={(e) => {
                const next = clampPercentValue(Number(e.target.value));
                setAvatarInsertStartPercent(Math.min(99, next));
              }}
              className="input-field w-full h-10 mt-1"
            />
          </div>
          <div>
            <label className="text-[11px] text-slate-600 font-semibold">Финиш вставок (%)</label>
            <input
              type="number"
              min={1}
              max={100}
              value={avatarInsertEndPercent}
              onChange={(e) => {
                const next = clampPercentValue(Number(e.target.value));
                setAvatarInsertEndPercent(Math.max(1, next));
              }}
              className="input-field w-full h-10 mt-1"
            />
          </div>
          <div>
            <label className="text-[11px] text-slate-600 font-semibold">Сколько вставок</label>
            <input
              type="number"
              min={0}
              max={20}
              value={avatarInsertClipsCount}
              onChange={(e) => {
                const value = Number(e.target.value);
                if (Number.isNaN(value)) return;
                setAvatarInsertClipsCount(Math.max(0, Math.min(20, Math.round(value))));
              }}
              className="input-field w-full h-10 mt-1"
            />
          </div>
        </div>

        <div className="p-3 rounded-xl border border-slate-200 bg-slate-50">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs font-bold text-slate-700 uppercase tracking-wider">Файлы для вставок</p>
            <button
              onClick={() => avatarInsertInputRef.current?.click()}
              disabled={uploadingAvatarInsertClip}
              className="h-8 px-3 rounded-lg bg-[#24a1de] text-white text-xs font-bold flex items-center gap-1 disabled:opacity-50"
            >
              {uploadingAvatarInsertClip ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />}
              Добавить видео
            </button>
          </div>

          {loadingAvatarInsertClips ? (
            <div className="h-32 rounded-lg border border-slate-200 bg-white flex items-center justify-center text-slate-400">
              <Loader2 size={16} className="animate-spin" />
            </div>
          ) : avatarInsertClips.length === 0 ? (
            <div className="h-32 rounded-lg border border-dashed border-slate-300 bg-white flex items-center justify-center text-xs text-slate-500">
              Видео-вставки не загружены
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
              {avatarInsertClips.slice(0, 9).map((clip) => (
                <div key={clip.id} className="relative rounded-lg overflow-hidden border border-slate-200 bg-white">
                  <video src={getMediaUrl(clip.file_path)} className="w-full h-24 object-cover" muted />
                  <button
                    onClick={() => handleDeleteAvatarInsertClip(clip.id)}
                    disabled={deletingAvatarInsertClipId === clip.id}
                    className="absolute top-1 right-1 h-6 w-6 rounded-md bg-black/70 text-white flex items-center justify-center disabled:opacity-50"
                  >
                    {deletingAvatarInsertClipId === clip.id ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                  </button>
                </div>
              ))}
            </div>
          )}
          <p className="text-[11px] text-slate-500 mt-2">
            Вставки размещаются автоматически после Remotion: максимально равномерно и с максимальной дистанцией между ними в выбранном диапазоне.
          </p>
        </div>
      </div>

      <div className="tg-card p-4">
        <div className="flex items-center gap-2 mb-3">
          <Film size={18} className="text-[#24a1de]" />
          <h3 className="text-[15px] font-bold text-slate-900">Reels B-roll из Яндекс.Диска</h3>
        </div>

        <div>
          <label className="text-[11px] text-slate-600 font-semibold">Доля b-roll от видео (%)</label>
          <input
            type="number"
            min={0}
            max={100}
            value={reelsBrollCoveragePercent}
            onChange={(e) => {
              const next = clampPercentValue(Number(e.target.value));
              setReelsBrollCoveragePercent(next);
            }}
            className="input-field w-full h-10 mt-1"
          />
          <p className="text-[11px] text-slate-500 mt-2">
            Если видео 10 секунд и стоит 50%, система вставит примерно 5 секунд b-roll. Одна вставка использует один случайный ролик с Яндекс.Диска, длина вставки 2.5-4 сек.
          </p>
        </div>
      </div>

      <div className="tg-card p-4">
        <div className="flex items-center gap-2 mb-3">
          <User size={18} className="text-[#24a1de]" />
          <h3 className="text-[15px] font-bold text-slate-900">Выбор ИИ Аватара (HeyGen)</h3>
        </div>
        
        {loadingAvatars ? (
          <div className="flex items-center justify-center py-6 text-slate-400">
            <Loader2 className="animate-spin w-5 h-5 mr-2" />
            <span className="text-sm">Загрузка аватаров...</span>
          </div>
        ) : heygenAvatars.length === 0 ? (
          <div className="text-center py-6 text-slate-400 italic text-sm">
            Аватары не найдены
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {heygenAvatars.map(avatar => (
              <div
                key={avatar.id}
                className={`relative cursor-pointer rounded-xl overflow-hidden border-2 transition-all h-32 ${
                  selectedAvatar === avatar.id || selectedVerticalAvatar === avatar.id ? 'border-[#24a1de] shadow-md' : 'border-transparent opacity-70 hover:opacity-100'
                }`}
              >
                {avatar.preview && avatar.preview.endsWith('.mp4') ? (
                  <video src={avatar.preview} className="w-full h-full object-cover bg-slate-100" muted onMouseOver={e => e.currentTarget.play()} onMouseOut={e => {e.currentTarget.pause(); e.currentTarget.currentTime = 0;}} />
                ) : (
                  <img src={avatar.preview || 'https://via.placeholder.com/150'} alt={avatar.name} className="w-full h-full object-cover bg-slate-100" />
                )}
                <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/90 via-black/40 to-transparent p-2">
                  <p className="text-white text-[11px] font-bold leading-tight truncate">{avatar.name}</p>
                  <p className="text-white/60 text-[8px] leading-tight truncate mt-0.5">{avatar.id}</p>
                </div>
                <div className="absolute top-2 right-2 flex flex-col gap-1">
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedAvatar(avatar.id);
                    }}
                    className={`px-2 h-6 rounded-md border text-[10px] font-bold shadow-sm ${
                      selectedAvatar === avatar.id
                        ? 'bg-[#24a1de] border-white text-white'
                        : 'bg-white/90 border-white text-slate-700'
                    }`}
                  >
                    YouTube
                  </button>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setSelectedVerticalAvatar(avatar.id);
                    }}
                    className={`px-2 h-6 rounded-md border text-[10px] font-bold shadow-sm ${
                      selectedVerticalAvatar === avatar.id
                        ? 'bg-emerald-500 border-white text-white'
                        : 'bg-white/90 border-white text-slate-700'
                    }`}
                  >
                    Shorts
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="tg-card p-4">
        <div className="flex items-center gap-2 mb-3">
          <Mic size={18} className="text-[#24a1de]" />
          <h3 className="text-[15px] font-bold text-slate-900">Голос диктора (ElevenLabs)</h3>
        </div>
        {loadingVoices ? (
          <div className="h-20 rounded-xl border border-slate-200 bg-slate-50 flex items-center justify-center text-slate-400">
            <Loader2 size={16} className="animate-spin mr-2" />
            <span className="text-sm">Загрузка и калибровка голосов...</span>
          </div>
        ) : clonedVoices.length === 0 ? (
          <div className="h-20 rounded-xl border border-dashed border-slate-300 bg-slate-50 flex items-center justify-center text-xs text-slate-500">
            Нет склонированных голосов
          </div>
        ) : (
          <div className="space-y-2">
            {clonedVoices.map(voice => (
              <button
                key={voice.id}
                type="button"
                onClick={() => setSelectedVoice(voice.id)}
                className={`w-full min-h-[64px] rounded-xl border px-3 py-2 text-left transition-all flex items-center justify-between gap-3 ${
                  selectedVoice === voice.id
                    ? 'border-[#24a1de] bg-sky-50 shadow-sm'
                    : 'border-slate-200 bg-slate-50 hover:bg-white'
                }`}
              >
                <span className="min-w-0">
                  <span className="block text-sm font-bold text-slate-900 truncate">{voice.name}</span>
                  <span className="block text-[11px] text-slate-500 mt-0.5">{formatVoiceSpeed(voice.speed)}</span>
                </span>
                <span className={`h-5 w-5 rounded-full border-2 flex items-center justify-center shrink-0 ${
                  selectedVoice === voice.id ? 'border-[#24a1de]' : 'border-slate-300'
                }`}>
                  {selectedVoice === voice.id && <span className="h-2.5 w-2.5 rounded-full bg-[#24a1de]" />}
                </span>
              </button>
            ))}
          </div>
        )}
        <p className="text-[11px] text-slate-500 mt-2">
          Скорость считается один раз на голос по демо-озвучке и дальше используется для расчёта длины сценария.
        </p>
      </div>

      <div className="tg-card p-4">
        <div className="flex items-center justify-between gap-3 mb-3">
          <div className="flex items-center gap-2">
            <Film size={18} className="text-[#24a1de]" />
            <h3 className="text-[15px] font-bold text-slate-900">Длина long YouTube сценария</h3>
          </div>
          <span className="text-sm font-black text-slate-900 whitespace-nowrap">{avatarScriptDurationMinutes} мин</span>
        </div>
        <input
          type="range"
          min="1"
          max="30"
          step="1"
          value={avatarScriptDurationMinutes}
          onChange={(e) => setAvatarScriptDurationMinutes(parseInt(e.target.value) || 5)}
          className="w-full"
        />
        <div className="flex justify-between text-[10px] font-bold text-slate-400 mt-1">
          <span>1 мин</span>
          <span>30 мин</span>
        </div>
        <p className="text-[11px] text-slate-500 mt-2">
          Минуты переводятся в символы по скорости выбранного голоса ElevenLabs.
        </p>
      </div>

      <div className="tg-card p-4 mt-6 border-t-4 border-slate-100">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2 text-slate-700">
            <BookOpen size={18} />
            <h3 className="text-[15px] font-bold uppercase tracking-tight">Обучение стилю (Gemini)</h3>
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <label className="text-xs font-bold text-[#707579] uppercase tracking-wider mb-2 block">
              Ссылка на YouTube канал
            </label>
            <div className="relative">
              <input
                type="text"
                placeholder="https://youtube.com/@channel"
                value={trainingSource}
                onChange={(e) => setTrainingSource(e.target.value)}
                className="input-field w-full h-11 pl-10"
              />
              <Link2 size={16} className="absolute left-3 top-3.5 text-slate-400" />
            </div>
            <p className="text-[11px] text-slate-500 mt-1.5">
              Система проанализирует видео с канала и создаст промпт для копирования стиля.
            </p>
          </div>

          <div className="flex gap-2">
            <div className="flex-1">
              <label className="text-xs font-bold text-[#707579] uppercase tracking-wider mb-2 block">
                Сколько видео анализировать
              </label>
              <select
                value={videoCount}
                onChange={(e) => setVideoCount(e.target.value)}
                className="input-field w-full h-11"
              >
                <option value="3">3 последних видео (Быстро)</option>
                <option value="5">5 последних видео (Оптимально)</option>
                <option value="10">10 последних видео (Глубоко)</option>
              </select>
            </div>
            <div className="flex items-end">
              <button
                onClick={trainStyle}
                disabled={!trainingSource || trainingStatus === 'loading'}
                className="h-11 px-5 bg-slate-900 text-white text-sm font-bold rounded-xl flex items-center justify-center gap-2 shadow-lg disabled:opacity-50"
              >
                {trainingStatus === 'loading' ? <Loader2 className="animate-spin" size={16} /> : <BookOpen size={16} />}
                Анализировать
              </button>
            </div>
          </div>

          {trainingStatus === 'success' && (
            <div className="p-3 bg-emerald-50 text-emerald-700 text-xs font-bold rounded-xl border border-emerald-100 flex items-center gap-2">
              <div className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse" />
              Стиль успешно обновлен
            </div>
          )}
          {trainingStatus === 'error' && (
            <div className="p-3 bg-rose-50 text-rose-700 text-xs font-bold rounded-xl border border-rose-100 flex items-center gap-2">
              <div className="w-1.5 h-1.5 bg-rose-500 rounded-full animate-pulse" />
              Ошибка при анализе канала
            </div>
          )}

          <div>
            <label className="text-xs font-bold text-[#707579] uppercase tracking-wider mb-2 flex items-center justify-between">
              <span>Текущий профиль стиля (Prompt)</span>
            </label>
            <textarea
              value={styleProfile}
              onChange={(e) => setStyleProfile(e.target.value)}
              placeholder="Здесь появится промпт со стилем, который будет передаваться в Gemini..."
              className="input-field text-xs font-mono min-h-[150px] leading-relaxed resize-y bg-slate-50"
            />
          </div>
        </div>
      </div>
    </motion.div>
  );
};
