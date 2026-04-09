import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Image as ImageIcon, Video, Type, Save, Check, Upload, Smartphone, CalendarClock, RefreshCcw, LayoutGrid, ChevronRight, X, Eye } from 'lucide-react';
import axios from 'axios';

type UserSettings = {
  font_name: string;
  font_size: number;
  font_color: string;
  subtitles_enabled: boolean;
  selected_plate_id?: number | null;
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

const App = () => {
  const [activeTab, setActiveTab] = useState('branding');
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showPreview, setShowPreview] = useState(false);

  const [font, setFont] = useState('Montserrat');
  const [fontSize, setFontSize] = useState(60);
  const [fontColor, setFontColor] = useState('#FFFFFF');
  const [subtitlesEnabled, setSubtitlesEnabled] = useState(true);
  const [plateFile, setPlateFile] = useState<File | null>(null);
  const [platePreviewUrl, setPlatePreviewUrl] = useState('');
  const [selectedPlateId, setSelectedPlateId] = useState<number | null>(null);
  const [uploadingPlate, setUploadingPlate] = useState(false);
  const [telegramId, setTelegramId] = useState('');
  const [tasks, setTasks] = useState<VideoTaskItem[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [scheduleInputs, setScheduleInputs] = useState<Record<number, string>>({});
  const [activeTaskId, setActiveTaskId] = useState<number | null>(null);
  const [publishAccounts, setPublishAccounts] = useState<PublishAccount[]>([]);
  const [channelsLoading, setChannelsLoading] = useState(false);

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const webApp = window.Telegram?.WebApp;
    if (webApp?.ready) webApp.ready();
    if (webApp?.expand) webApp.expand();

    const tgUserId = webApp?.initDataUnsafe?.user?.id;
    if (tgUserId) {
      setTelegramId(String(tgUserId));
    } else {
      setTelegramId('12345678');
    }
  }, []);

  useEffect(() => {
    if (!telegramId) return;
    const loadSettings = async () => {
      try {
        const response = await axios.get<UserSettings>(`${API_BASE}/settings/${telegramId}`);
        setFont(response.data.font_name || 'Montserrat');
        setFontSize(response.data.font_size || 60);
        setFontColor(response.data.font_color ? `#${response.data.font_color.replace('#', '')}` : '#FFFFFF');
        setSubtitlesEnabled(response.data.subtitles_enabled !== false);
        setSelectedPlateId(response.data.selected_plate_id ?? null);
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
    } catch (error) {} finally {
      setChannelsLoading(false);
    }
  };

  const togglePublishAccount = async (accountId: number) => {
    if (!telegramId) return;
    const nextAccounts = publishAccounts.map((item) =>
      item.account_id === accountId ? { ...item, enabled: !item.enabled } : item,
    );
    setPublishAccounts(nextAccounts);
    const selected = nextAccounts.filter((item) => item.enabled).map((item) => item.account_id);
    try {
      await axios.post(`${API_BASE}/postmypost/channels/${telegramId}`, { account_ids: selected });
    } catch (error) {}
  };

  useEffect(() => {
    if (!telegramId) return;
    void loadTasks(telegramId);
    void loadPublishAccounts(telegramId);
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

  const handleSave = async () => {
    if (!telegramId) return;
    setLoading(true);
    try {
      await axios.post(`${API_BASE}/settings/${telegramId}/update`, {
        font_name: font,
        font_size: fontSize,
        font_color: fontColor.replace('#', ''),
        subtitles_enabled: subtitlesEnabled,
        selected_plate_id: selectedPlateId,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
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

  return (
    <div className="min-h-screen pb-32 flex flex-col items-center">
      {/* Header */}
      <header className="w-full bg-white px-4 py-3 flex items-center justify-between border-b sticky top-0 z-50">
        <h1 className="text-[17px] font-bold">Студия контента</h1>
        <button onClick={handleSave} disabled={loading} className="text-[16px] font-semibold text-[#24a1de] disabled:opacity-50">
          {loading ? '...' : saved ? 'Сохранено' : 'Сохранить'}
        </button>
      </header>

      <main className="w-full max-w-2xl px-4 py-6">
        <AnimatePresence mode="wait">
          {activeTab === 'branding' && (
            <motion.div key="branding" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-6">
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
            </motion.div>
          )}

          {activeTab === 'subtitles' && (
            <motion.div key="subtitles" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-6">
              <div className="tg-card">
                <div className="p-4 border-b">
                  <h3 className="text-[15px] font-bold uppercase text-[#707579] tracking-tight">Типографика</h3>
                </div>
                <div className="p-4 space-y-8">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-[#707579]">Субтитры включены</span>
                    <button
                      onClick={() => setSubtitlesEnabled((prev) => !prev)}
                      className={`w-12 h-6 rounded-full transition-all flex items-center p-1 ${subtitlesEnabled ? 'bg-[#34c759]' : 'bg-[#e9e9eb]'}`}
                    >
                      <div className={`w-4 h-4 bg-white rounded-full shadow-sm transform transition-all ${subtitlesEnabled ? 'translate-x-6' : 'translate-x-0'}`} />
                    </button>
                  </div>

                  <div className="space-y-3">
                    <div className="flex justify-between items-center text-sm font-medium">
                      <span className="text-[#707579]">Семейство шрифта</span>
                      <span className="text-[#24a1de] uppercase tracking-wider text-xs">{font}</span>
                    </div>
                    <select value={font} onChange={(e) => setFont(e.target.value)} className="w-full input-field appearance-none" disabled={!subtitlesEnabled}>
                      {['Montserrat', 'Inter', 'Outfit', 'Bangers', 'Roboto'].map(f => (<option key={f}>{f}</option>))}
                    </select>
                  </div>

                  <div className="space-y-4">
                    <div className="flex justify-between items-center text-sm font-medium">
                      <span className="text-[#707579]">Размер текста</span>
                      <span className="text-[#24a1de]">{fontSize}px</span>
                    </div>
                    <input type="range" min="20" max="120" value={fontSize} onChange={(e) => setFontSize(parseInt(e.target.value, 10))} className="w-full" disabled={!subtitlesEnabled} />
                  </div>

                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-[#707579]">Цвет текста</span>
                    <div className="flex items-center gap-3">
                       <span className="text-xs font-mono text-[#707579]">{fontColor.toUpperCase()}</span>
                       <input type="color" value={fontColor} onChange={(e) => setFontColor(e.target.value)} className="w-8 h-8 rounded-full overflow-hidden p-0 border-none cursor-pointer" disabled={!subtitlesEnabled} />
                    </div>
                  </div>
                </div>
              </div>
            </motion.div>
          )}

          {activeTab === 'schedule' && (
            <motion.div key="schedule" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-6">
              <div className="tg-card overflow-hidden">
                 <div className="p-4 border-b flex items-center justify-between">
                    <h3 className="text-[15px] font-bold uppercase text-[#707579] tracking-tight">Каналы публикации</h3>
                    <button onClick={() => telegramId && loadPublishAccounts(telegramId)} className="text-[#24a1de]"><RefreshCcw size={16} /></button>
                 </div>
                 <div className="divide-y">
                    {publishAccounts.map(acc => (
                      <div key={acc.account_id} className="p-4 flex items-center justify-between">
                         <div>
                            <p className="font-semibold text-[15px]">{acc.account_name}</p>
                            <p className="text-[12px] text-[#707579]">{acc.channel_name || 'Instagram/TikTok'}</p>
                         </div>
                         <button onClick={() => togglePublishAccount(acc.account_id)} className={`w-12 h-6 rounded-full transition-all flex items-center p-1 ${acc.enabled ? 'bg-[#34c759]' : 'bg-[#e9e9eb]'}`}>
                            <div className={`w-4 h-4 bg-white rounded-full shadow-sm transform transition-all ${acc.enabled ? 'translate-x-6' : 'translate-x-0'}`} />
                         </button>
                      </div>
                    ))}
                 </div>
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
      <button onClick={() => setShowPreview(true)} className="fab-preview">
        <Eye size={24} />
      </button>

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
                  style={{ 
                    fontFamily: font, 
                    fontSize: `${fontSize / 4.5}vw`, 
                    color: fontColor,
                    textShadow: '0 2px 4px rgba(0,0,0,0.3)'
                  }} 
                  className="text-center font-black uppercase leading-[1.1]"
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
            <p className="mt-4 text-[11px] font-bold text-white uppercase tracking-widest bg-black/20 px-3 py-1 rounded-full backdrop-blur-sm">Предпросмотр активен</p>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Bottom Navigation Dock */}
      <nav className="bottom-nav">
        {[
          { id: 'branding', icon: ImageIcon, label: 'Брендинг' },
          { id: 'subtitles', icon: Type, label: 'Субтитры' },
          { id: 'schedule', icon: CalendarClock, label: 'Очередь' },
          { id: 'all', icon: LayoutGrid, label: 'Настройки' }
        ].map(tab => (
          <button 
            key={tab.id}
            onClick={() => setActiveTab(tab.id === 'all' ? 'branding' : tab.id)}
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
