import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Settings, Image as ImageIcon, Video, Type, Save, Check, Upload, Smartphone, Monitor, Palette, CalendarClock, RefreshCcw } from 'lucide-react';
import axios from 'axios';

type UserSettings = {
  font_name: string;
  font_size: number;
  font_color: string;
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
  const [statusText, setStatusText] = useState('');

  const [font, setFont] = useState('Montserrat');
  const [fontSize, setFontSize] = useState(60);
  const [fontColor, setFontColor] = useState('#FFFFFF');
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
      setStatusText('Using Demo ID: 12345678');
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
        setSelectedPlateId(response.data.selected_plate_id ?? null);
      } catch (error) {
        setStatusText('Load failed. Settings default values applied.');
      }
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
      setStatusText('Failed to load scheduled content list.');
    } finally {
      setTasksLoading(false);
    }
  };

  const loadPublishAccounts = async (targetTelegramId: string) => {
    setChannelsLoading(true);
    try {
      const response = await axios.get<PublishAccount[]>(`${API_BASE}/postmypost/channels/${targetTelegramId}`);
      setPublishAccounts(response.data);
    } catch (error) {
      setStatusText('Failed to load publish channels.');
    } finally {
      setChannelsLoading(false);
    }
  };

  const savePublishAccounts = async (targetTelegramId: string, nextAccounts: PublishAccount[]) => {
    const selected = nextAccounts.filter((item) => item.enabled).map((item) => item.account_id);
    try {
      const response = await axios.post<PublishAccount[]>(
        `${API_BASE}/postmypost/channels/${targetTelegramId}`,
        { account_ids: selected },
      );
      setPublishAccounts(response.data);
      setStatusText('Channels updated.');
    } catch (error) {
      setStatusText('Failed to update channels.');
    }
  };

  useEffect(() => {
    if (!telegramId) return;
    void loadTasks(telegramId);
    void loadPublishAccounts(telegramId);
  }, [telegramId]);

  const publishingStatusLabel = (value: string) => {
    if (value === 'scheduled') return 'Scheduled';
    if (value === 'in_progress') return 'Publishing';
    if (value === 'published') return 'Published';
    if (value === 'failed') return 'Failed';
    return 'Not scheduled';
  };

  const statusBadgeClass = (value: string) => {
    if (value === 'scheduled') return 'bg-blue-500/15 text-blue-400 border-blue-500/30';
    if (value === 'in_progress') return 'bg-yellow-500/15 text-yellow-400 border-yellow-500/30';
    if (value === 'published') return 'bg-green-500/15 text-green-400 border-green-500/30';
    if (value === 'failed') return 'bg-red-500/15 text-red-400 border-red-500/30';
    return 'bg-slate-500/15 text-slate-300 border-slate-500/30';
  };

  const saveTaskSchedule = async (taskId: number) => {
    if (!telegramId) return;
    const localValue = scheduleInputs[taskId];
    if (!localValue) {
      setStatusText('Choose date and time before scheduling.');
      return;
    }
    const publishAt = new Date(localValue);
    if (Number.isNaN(publishAt.getTime())) {
      setStatusText('Invalid schedule date format.');
      return;
    }

    setActiveTaskId(taskId);
    try {
      await axios.patch(`${API_BASE}/tasks/${telegramId}/${taskId}/schedule`, {
        publish_at: publishAt.toISOString(),
      });
      await loadTasks(telegramId);
      setStatusText('Schedule updated.');
    } catch (error) {
      setStatusText('Failed to update schedule.');
    } finally {
      setActiveTaskId(null);
    }
  };

  const clearTaskSchedule = async (taskId: number) => {
    if (!telegramId) return;
    setActiveTaskId(taskId);
    try {
      await axios.patch(`${API_BASE}/tasks/${telegramId}/${taskId}/schedule`, {
        publish_at: null,
      });
      await loadTasks(telegramId);
      setStatusText('Schedule removed.');
    } catch (error) {
      setStatusText('Failed to remove schedule.');
    } finally {
      setActiveTaskId(null);
    }
  };

  const publishTaskNow = async (taskId: number) => {
    if (!telegramId) return;
    setActiveTaskId(taskId);
    try {
      await axios.post(`${API_BASE}/tasks/${telegramId}/${taskId}/publish-now`);
      await loadTasks(telegramId);
      setStatusText('Publishing started.');
    } catch (error) {
      setStatusText('Cannot publish now. Task may not be completed yet.');
    } finally {
      setActiveTaskId(null);
    }
  };

  const togglePublishAccount = async (accountId: number) => {
    if (!telegramId) return;
    const nextAccounts = publishAccounts.map((item) =>
      item.account_id === accountId ? { ...item, enabled: !item.enabled } : item,
    );
    setPublishAccounts(nextAccounts);
    await savePublishAccounts(telegramId, nextAccounts);
  };

  const handlePickFile = () => fileInputRef.current?.click();

  const handlePlateSelected = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !telegramId) return;
    
    if (!['image/png', 'image/webp'].includes(file.type)) {
      setStatusText('Error: Please use PNG or WEBP (transparent support).');
      return;
    }

    if (platePreviewUrl) URL.revokeObjectURL(platePreviewUrl);
    const objectUrl = URL.createObjectURL(file);
    setPlatePreviewUrl(objectUrl);
    setPlateFile(file);

    const formData = new FormData();
    formData.append('file', file);
    setUploadingPlate(true);

    try {
      const response = await axios.post<{ plate_id: number }>(
        `${API_BASE}/upload/plate/${telegramId}`,
        formData,
        { headers: { 'Content-Type': 'multipart/form-data' } }
      );
      setSelectedPlateId(response.data.plate_id);
    } catch (error) {
      setStatusText('Upload failed. Try again.');
    } finally {
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
        selected_plate_id: selectedPlateId,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (error) {
      setStatusText('Save failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-4 py-8 lg:px-8">
      <div className="flex flex-col lg:flex-row gap-12">
        {/* Left Col: Settings */}
        <div className="flex-1 space-y-8 animate-in fade-in slide-in-from-left duration-700">
          <header className="flex items-center gap-4 mb-8">
            <div className="p-3 bg-blue-500/10 rounded-2xl">
              <Monitor className="text-blue-500" size={24} />
            </div>
            <div>
              <h1 className="text-3xl font-extrabold tracking-tight">Content Studio <span className="text-xs font-medium px-2 py-0.5 bg-blue-500/20 text-blue-400 rounded-full align-middle ml-2">BETA</span></h1>
              <p className="text-slate-400">Professional branding for your social clips</p>
            </div>
          </header>

          <div className="flex bg-slate-900/50 p-1.5 rounded-2xl border border-white/5 backdrop-blur-md">
            {[
              { id: 'branding', icon: ImageIcon, label: 'Branding' },
              { id: 'subtitles', icon: Type, label: 'Subtitles' },
              { id: 'cta', icon: Video, label: 'CTA Manager' },
              { id: 'schedule', icon: CalendarClock, label: 'Schedule' }
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex-1 flex items-center justify-center gap-2.5 py-3 rounded-xl transition-all duration-300 ${activeTab === tab.id ? 'bg-blue-600 text-white shadow-lg shadow-blue-600/20' : 'text-slate-400 hover:text-white hover:bg-white/5'}`}
              >
                <tab.icon size={18} />
                <span className="text-sm font-semibold">{tab.label}</span>
              </button>
            ))}
          </div>

          <div className="glass-panel p-8 rounded-[32px] min-h-[500px]">
            <AnimatePresence mode="wait">
              {activeTab === 'branding' && (
                <motion.div
                  key="branding"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  className="space-y-8"
                >
                  <div>
                    <h3 className="text-xl font-bold mb-2">Overlay Plate</h3>
                    <p className="text-slate-400 text-sm">Upload a PNG/WEBP with transparency. This will be placed in the top corner of your videos.</p>
                  </div>

                  <input ref={fileInputRef} type="file" accept="image/png,image/webp" onChange={handlePlateSelected} className="hidden" />

                  <div 
                    onClick={handlePickFile}
                    className="group w-full aspect-video rounded-3xl border-2 border-dashed border-slate-800 bg-white/[0.02] flex flex-col items-center justify-center gap-4 hover:border-blue-500/50 hover:bg-blue-500/[0.02] transition-all cursor-pointer relative overflow-hidden"
                  >
                    <div className="bg-blue-500/10 p-5 rounded-full group-hover:scale-110 transition-transform duration-500">
                      <Upload className="text-blue-500" />
                    </div>
                    <div className="text-center">
                      <p className="font-bold text-lg">{uploadingPlate ? 'Processing...' : 'Click to Upload Plate'}</p>
                      <p className="text-xs text-slate-500 mt-1 uppercase tracking-widest">Max file size 5MB</p>
                    </div>
                  </div>
                  
                  {plateFile && (
                    <div className="flex items-center gap-3 p-4 bg-white/[0.03] rounded-2xl border border-white/5">
                      <div className="p-2 bg-green-500/10 rounded-lg">
                        <Check className="text-green-500" size={16} />
                      </div>
                      <span className="text-sm text-slate-300 font-medium truncate">{plateFile.name}</span>
                    </div>
                  )}
                </motion.div>
              )}

              {activeTab === 'subtitles' && (
                <motion.div
                  key="subtitles"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  className="space-y-10"
                >
                  <div>
                    <h3 className="text-xl font-bold mb-2">Typography & Style</h3>
                    <p className="text-slate-400 text-sm">Fine-tune the look and feel of your automated captions.</p>
                  </div>

                  <div className="grid gap-8 lg:grid-cols-2">
                    <div className="space-y-3">
                      <label className="text-xs font-bold text-slate-500 uppercase tracking-widest">Font Family</label>
                      <select value={font} onChange={(e) => setFont(e.target.value)} className="w-full input-field text-white appearance-none cursor-pointer">
                        {['Montserrat', 'Inter', 'Outfit', 'Bangers', 'Roboto'].map(f => (
                          <option key={f} className="bg-slate-900 border-none">{f}</option>
                        ))}
                      </select>
                    </div>

                    <div className="space-y-3">
                      <label className="text-xs font-bold text-slate-500 uppercase tracking-widest">Text Color</label>
                      <div className="flex items-center gap-4">
                        <input type="color" value={fontColor} onChange={(e) => setFontColor(e.target.value)} className="h-10 w-16 bg-transparent border-none p-0 cursor-pointer" />
                        <span className="font-mono text-sm uppercase text-slate-400">{fontColor}</span>
                      </div>
                    </div>
                  </div>

                  <div className="space-y-6">
                    <div className="flex justify-between items-center">
                      <label className="text-xs font-bold text-slate-500 uppercase tracking-widest">Font Size</label>
                      <span className="text-xl font-black text-blue-500">{fontSize}<small className="text-[10px] ml-1">PX</small></span>
                    </div>
                    <input type="range" min="20" max="120" value={fontSize} onChange={(e) => setFontSize(parseInt(e.target.value, 10))} className="w-full" />
                  </div>
                </motion.div>
              )}

              {activeTab === 'cta' && (
                <motion.div
                  key="cta"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  className="flex flex-col items-center justify-center min-h-[300px] text-center"
                >
                  <div className="p-6 bg-yellow-500/10 rounded-3xl mb-4">
                    <Palette className="text-yellow-500" size={32} />
                  </div>
                  <h3 className="text-xl font-bold mb-2">Coming Soon</h3>
                  <p className="text-slate-400 text-sm max-w-xs">Dynamic Call-to-Action video manager is currently under development.</p>
                </motion.div>
              )}

              {activeTab === 'schedule' && (
                <motion.div
                  key="schedule"
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  className="space-y-4"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h3 className="text-xl font-bold mb-1">Content Schedule</h3>
                      <p className="text-slate-400 text-sm">Set publish time for completed videos and manage queue status.</p>
                    </div>
                    <button
                      onClick={() => {
                        if (!telegramId) return;
                        void loadTasks(telegramId);
                        void loadPublishAccounts(telegramId);
                      }}
                      className="px-3 py-2 rounded-xl border border-white/10 text-slate-300 hover:bg-white/5 transition-colors text-xs font-semibold uppercase tracking-wider"
                    >
                      <span className="inline-flex items-center gap-2"><RefreshCcw size={14} />Refresh</span>
                    </button>
                  </div>

                  <div className="p-4 rounded-2xl border border-white/10 bg-white/[0.02] space-y-3">
                    <div className="text-xs text-slate-500 uppercase tracking-widest">PostMyPost Channels</div>
                    {channelsLoading && (
                      <div className="text-sm text-slate-400">Loading channels...</div>
                    )}
                    {!channelsLoading && publishAccounts.length === 0 && (
                      <div className="text-sm text-slate-400">No channels/accounts found. Check `POSTMYPOST_API_KEY` and `POSTMYPOST_PROJECT_ID`.</div>
                    )}
                    {!channelsLoading && publishAccounts.length > 0 && (
                      <div className="space-y-2">
                        {publishAccounts.map((account) => (
                          <div key={account.account_id} className="flex items-center justify-between gap-3 p-3 rounded-xl border border-white/10 bg-black/20">
                            <div className="min-w-0">
                              <div className="text-sm text-slate-100 truncate">{account.account_name}</div>
                              <div className="text-xs text-slate-500 truncate">
                                {account.channel_name || account.channel_code || 'Unknown channel'}
                                {account.account_login ? ` · ${account.account_login}` : ''}
                              </div>
                            </div>
                            <button
                              onClick={() => togglePublishAccount(account.account_id)}
                              className={`w-11 h-6 rounded-full p-1 transition-colors ${account.enabled ? 'bg-blue-500' : 'bg-slate-700'}`}
                            >
                              <div className={`w-4 h-4 bg-white rounded-full transition-transform ${account.enabled ? 'translate-x-5' : 'translate-x-0'}`} />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {tasksLoading && (
                    <div className="text-sm text-slate-400">Loading tasks...</div>
                  )}

                  {!tasksLoading && tasks.length === 0 && (
                    <div className="p-5 rounded-2xl border border-white/10 bg-white/[0.02] text-sm text-slate-400">
                      No tasks yet. Send a video link to the bot first.
                    </div>
                  )}

                  <div className="space-y-3 max-h-[420px] overflow-auto pr-1">
                    {tasks.map(task => (
                      <div key={task.id} className="p-4 rounded-2xl border border-white/10 bg-white/[0.02] space-y-3">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="text-xs text-slate-500 uppercase tracking-widest mb-1">Task #{task.id} · {task.type}</div>
                            <div className="text-sm text-slate-200 truncate">{task.source_url}</div>
                            <div className="text-xs text-slate-500 mt-1">Pipeline status: {task.status}</div>
                          </div>
                          <span className={`text-xs px-2 py-1 rounded-lg border ${statusBadgeClass(task.publishing_status)}`}>
                            {publishingStatusLabel(task.publishing_status)}
                          </span>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                          <input
                            type="datetime-local"
                            value={scheduleInputs[task.id] || ''}
                            onChange={(e) => setScheduleInputs(prev => ({ ...prev, [task.id]: e.target.value }))}
                            className="input-field text-white"
                          />
                          <div className="text-xs text-slate-500 flex items-center">
                            {task.publish_at ? `Current: ${new Date(task.publish_at).toLocaleString()}` : 'Not scheduled'}
                          </div>
                        </div>

                        <div className="flex flex-wrap gap-2">
                          <button
                            onClick={() => saveTaskSchedule(task.id)}
                            disabled={activeTaskId === task.id}
                            className="px-3 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold disabled:opacity-60"
                          >
                            Save schedule
                          </button>
                          <button
                            onClick={() => clearTaskSchedule(task.id)}
                            disabled={activeTaskId === task.id}
                            className="px-3 py-2 rounded-xl border border-white/15 text-slate-300 hover:bg-white/5 text-xs font-semibold disabled:opacity-60"
                          >
                            Remove schedule
                          </button>
                          <button
                            onClick={() => publishTaskNow(task.id)}
                            disabled={activeTaskId === task.id || task.status !== 'completed'}
                            className="px-3 py-2 rounded-xl border border-green-500/30 text-green-400 hover:bg-green-500/10 text-xs font-semibold disabled:opacity-50"
                          >
                            Publish now
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          <div className="flex flex-col gap-4">
            {statusText && (
              <p className="text-sm text-slate-400 text-center animate-pulse">{statusText}</p>
            )}
            <button
              onClick={handleSave}
              disabled={loading}
              className="w-full btn-primary flex items-center justify-center gap-3 group relative overflow-hidden"
            >
              {loading ? (
                <div className="w-5 h-5 border-2 border-white/20 border-t-white rounded-full animate-spin" />
              ) : saved ? (
                <><Check size={20} className="animate-bounce" /> Configuration Saved!</>
              ) : (
                <><Save size={20} className="group-hover:scale-110 transition-transform" /> Sync All Changes</>
              )}
            </button>
          </div>
        </div>

        {/* Right Col: Live Preview */}
        <div className="lg:w-1/3 flex flex-col items-center">
          <div className="sticky top-8 space-y-6 flex flex-col items-center">
            <div className="flex items-center gap-2 mb-2 px-4 py-1.5 bg-slate-900/80 border border-white/5 rounded-full backdrop-blur-xl">
              <Smartphone size={14} className="text-blue-500" />
              <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">Live 9:16 Preview</span>
            </div>

            <div className="phone-frame animate-in fade-in zoom-in duration-1000">
              <div className="phone-notch"></div>
              
              {/* Background Layer */}
              <div className="absolute inset-0 bg-slate-800">
                <div className="absolute inset-0 bg-[url('https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?auto=format&fit=crop&q=80')] bg-cover bg-center brightness-50 contrast-125" />
                <div className="absolute inset-0 bg-gradient-to-t from-black via-transparent to-black/20" />
              </div>

              {/* Plate Overlay Layer */}
              <div className="absolute top-8 left-0 right-0 px-6 flex justify-end">
                {platePreviewUrl ? (
                  <img src={platePreviewUrl} className="max-w-[40%] h-auto drop-shadow-2xl animate-in fade-in duration-500" />
                ) : (
                  <div className="w-16 h-16 bg-white/10 rounded-xl border border-white/5 backdrop-blur-md flex items-center justify-center">
                    <ImageIcon className="text-white/20" size={20} />
                  </div>
                )}
              </div>

              {/* Subtitles Layer */}
              <div className="absolute inset-0 flex items-center justify-center px-6 pointer-events-none">
                <div className="w-full text-center">
                   <motion.div
                     key={`${font}-${fontSize}-${fontColor}`}
                     initial={{ opacity: 0, scale: 0.9 }}
                     animate={{ opacity: 1, scale: 1 }}
                     style={{ 
                       fontFamily: font, 
                       fontSize: `${fontSize / 3.5}vw`, 
                       color: fontColor,
                       textShadow: '0 4px 12px rgba(0,0,0,0.5), 0 0 40px rgba(0,0,0,0.2)'
                     }}
                     className="font-black leading-tight tracking-tight uppercase"
                   >
                     Make your content<br />
                     <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-blue-600">Stand out</span><br />
                     In 2026
                   </motion.div>
                </div>
              </div>

              {/* UI Emulation Bottom */}
              <div className="absolute bottom-12 left-0 right-0 px-6 space-y-4">
                 <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-full bg-slate-400 border border-white/20" />
                    <div className="flex-1 space-y-1">
                       <div className="w-20 h-2 bg-white/20 rounded" />
                       <div className="w-12 h-1.5 bg-white/10 rounded" />
                    </div>
                 </div>
                 <div className="flex gap-4">
                    <div className="w-8 h-8 rounded-full bg-white/10 backdrop-blur-lg flex items-center justify-center">
                       <div className="w-4 h-4 rounded-full border border-white/20" />
                    </div>
                    <div className="w-8 h-8 rounded-full bg-white/10 backdrop-blur-lg" />
                 </div>
              </div>
            </div>

            <div className="text-center space-y-1 opacity-40">
              <p className="text-[10px] font-bold uppercase tracking-widest">Auto-Rendering Engine v2.4</p>
              <p className="text-[8px] font-medium uppercase tracking-tighter">Real-time sync enabled</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default App;
