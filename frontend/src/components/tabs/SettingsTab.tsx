import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Settings, Save, Loader2, Link2, BookOpen, User, Mic } from 'lucide-react';
import { apiClient } from '../../api/client';
import { useTelegram } from '../../context/TelegramContext';

export const SettingsTab: React.FC = () => {
  const { telegramId } = useTelegram();
  const [styleProfile, setStyleProfile] = useState('');
  const [trainingSource, setTrainingSource] = useState('');
  const [videoCount, setVideoCount] = useState('5');
  const [trainingStatus, setTrainingStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [loadingStyle, setLoadingStyle] = useState(false);
  
  const [clonedVoices, setClonedVoices] = useState<{id: string, name: string}[]>([]);
  const [loadingVoices, setLoadingVoices] = useState(false);
  const [heygenAvatars, setHeygenAvatars] = useState<{id: string, name: string, preview: string}[]>([]);
  const [loadingAvatars, setLoadingAvatars] = useState(false);
  const [selectedAvatar, setSelectedAvatar] = useState<string>('');
  const [selectedVoice, setSelectedVoice] = useState<string>('');
  const [savingSettings, setSavingSettings] = useState(false);
  const [savedSettings, setSavedSettings] = useState(false);

  useEffect(() => {
    const loadStyle = async () => {
      if (!telegramId) return;
      setLoadingStyle(true);
      try {
        const data = await apiClient.getStyleSettings(telegramId);
        setStyleProfile(data.author_style_profile || '');
        setTrainingSource(data.training_source || '');
        if (data.heygen_avatar_id) setSelectedAvatar(data.heygen_avatar_id);
        if (data.elevenlabs_voice_id) setSelectedVoice(data.elevenlabs_voice_id);
      } catch (error) {
      } finally {
        setLoadingStyle(false);
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
            name: v.name
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
    setSavingSettings(true);
    try {
      await apiClient.updateSettings(telegramId, {
        author_style_profile: styleProfile,
        heygen_avatar_id: selectedAvatar,
        elevenlabs_voice_id: selectedVoice
      });
      setSavedSettings(true);
      setTimeout(() => setSavedSettings(false), 2000);
    } catch (error) {
    } finally {
      setSavingSettings(false);
    }
  };

  const avatars = [
    { id: 'Wayne_20240711', name: 'Wayne', desc: 'Строгий, деловой', img: 'https://cdn2.heygen.ai/avatar/v3/Wayne_20240711/preview.jpg' },
    { id: 'Joshua_20240711', name: 'Joshua', desc: 'Харизматичный', img: 'https://cdn2.heygen.ai/avatar/v3/Joshua_20240711/preview.jpg' },
    { id: 'Bella_20240711', name: 'Bella', desc: 'Дружелюбная', img: 'https://cdn2.heygen.ai/avatar/v3/Bella_20240711/preview.jpg' }
  ];

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
                onClick={() => setSelectedAvatar(avatar.id)}
                className={`relative cursor-pointer rounded-xl overflow-hidden border-2 transition-all h-32 ${
                  selectedAvatar === avatar.id ? 'border-[#24a1de] shadow-md' : 'border-transparent opacity-70 hover:opacity-100'
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
                {selectedAvatar === avatar.id && (
                  <div className="absolute top-2 right-2 w-5 h-5 bg-[#24a1de] rounded-full border-2 border-white flex items-center justify-center shadow-sm">
                    <div className="w-2 h-2 bg-white rounded-full"></div>
                  </div>
                )}
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
        <select
          value={selectedVoice}
          onChange={(e) => setSelectedVoice(e.target.value)}
          disabled={loadingVoices}
          className="input-field w-full h-12 text-[15px] font-medium appearance-none bg-slate-50 disabled:opacity-50"
          style={{ backgroundImage: 'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'24\' height=\'24\' viewBox=\'0 0 24 24\' fill=\'none\' stroke=\'%2394a3b8\' stroke-width=\'2\' stroke-linecap=\'round\' stroke-linejoin=\'round\'%3E%3Cpolyline points=\'6 9 12 15 18 9\'%3E%3C/polyline%3E%3C/svg%3E")', backgroundRepeat: 'no-repeat', backgroundPosition: 'right 12px center', backgroundSize: '16px' }}
        >
          {loadingVoices ? (
            <option value="">Загрузка голосов...</option>
          ) : clonedVoices.length === 0 ? (
            <option value="">Нет склонированных голосов</option>
          ) : (
            clonedVoices.map(voice => (
              <option key={voice.id} value={voice.id}>{voice.name}</option>
            ))
          )}
        </select>
        <p className="text-[11px] text-slate-500 mt-2">
          Этот голос будет использоваться при генерации новых ИИ-видео.
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
