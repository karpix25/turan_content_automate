import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Settings, Image as ImageIcon, Video, Type, Save, Check, Upload } from 'lucide-react';
import axios from 'axios';

type UserSettings = {
  font_name: string;
  font_size: number;
  font_color: string;
  selected_plate_id?: number | null;
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

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const webApp = window.Telegram?.WebApp;
    if (webApp?.ready) {
      webApp.ready();
    }
    if (webApp?.expand) {
      webApp.expand();
    }

    const tgUserId = webApp?.initDataUnsafe?.user?.id;
    if (tgUserId) {
      setTelegramId(String(tgUserId));
      return;
    }

    setTelegramId('12345678');
    setStatusText('Telegram user id not found. Using fallback id 12345678.');
  }, []);

  useEffect(() => {
    if (!telegramId) {
      return;
    }

    const loadSettings = async () => {
      try {
        const response = await axios.get<UserSettings>(`${API_BASE}/settings/${telegramId}`);
        setFont(response.data.font_name || 'Montserrat');
        setFontSize(response.data.font_size || 60);
        setFontColor(response.data.font_color ? `#${response.data.font_color.replace('#', '')}` : '#FFFFFF');
        setSelectedPlateId(response.data.selected_plate_id ?? null);
      } catch (error) {
        setStatusText('Failed to load saved settings.');
      }
    };

    void loadSettings();
  }, [telegramId]);

  useEffect(() => {
    return () => {
      if (platePreviewUrl) {
        URL.revokeObjectURL(platePreviewUrl);
      }
    };
  }, [platePreviewUrl]);

  const handlePickFile = () => {
    fileInputRef.current?.click();
  };

  const handlePlateSelected = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    if (!telegramId) {
      setStatusText('Telegram id is not ready yet.');
      return;
    }
    if (!['image/png', 'image/webp'].includes(file.type)) {
      setStatusText('Only PNG or WEBP files are supported.');
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setStatusText('File is too large. Max 5MB.');
      return;
    }

    if (platePreviewUrl) {
      URL.revokeObjectURL(platePreviewUrl);
    }
    const objectUrl = URL.createObjectURL(file);
    setPlatePreviewUrl(objectUrl);
    setPlateFile(file);

    const formData = new FormData();
    formData.append('file', file);
    setUploadingPlate(true);
    setStatusText('Uploading plate...');

    try {
      const response = await axios.post<{ plate_id: number }>(
        `${API_BASE}/upload/plate/${telegramId}`,
        formData,
        {
          headers: { 'Content-Type': 'multipart/form-data' },
        }
      );
      setSelectedPlateId(response.data.plate_id);
      setStatusText('Plate uploaded. Save settings to apply it.');
    } catch (error) {
      setStatusText('Failed to upload plate.');
    } finally {
      setUploadingPlate(false);
      event.target.value = '';
    }
  };

  const handleSave = async () => {
    if (!telegramId) {
      setStatusText('Telegram id is not ready yet.');
      return;
    }

    setLoading(true);
    setStatusText('');
    try {
      await axios.post(`${API_BASE}/settings/${telegramId}/update`, {
        font_name: font,
        font_size: fontSize,
        font_color: fontColor.replace('#', ''),
        selected_plate_id: selectedPlateId,
      });
      setSaved(true);
      setStatusText('Settings saved.');
      setTimeout(() => setSaved(false), 3000);
    } catch (error) {
      setStatusText('Failed to save settings.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen p-4 max-w-md mx-auto pb-32">
      <header className="flex justify-between items-center mb-8 pt-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Content Studio</h1>
          <p className="text-gray-400 text-sm">Customize your social clips</p>
        </div>
        <div className="bg-blue-500/10 p-2 rounded-full">
          <Settings className="text-blue-500" size={20} />
        </div>
      </header>

      <div className="flex bg-black/30 rounded-2xl p-1 mb-6">
        <button
          onClick={() => setActiveTab('branding')}
          className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl transition-all ${activeTab === 'branding' ? 'bg-blue-500 text-white shadow-lg' : 'text-gray-400'}`}
        >
          <ImageIcon size={18} /> <span className="text-sm font-medium">Branding</span>
        </button>
        <button
          onClick={() => setActiveTab('subtitles')}
          className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl transition-all ${activeTab === 'subtitles' ? 'bg-blue-500 text-white shadow-lg' : 'text-gray-400'}`}
        >
          <Type size={18} /> <span className="text-sm font-medium">Subtitles</span>
        </button>
        <button
          onClick={() => setActiveTab('cta')}
          className={`flex-1 flex items-center justify-center gap-2 py-2.5 rounded-xl transition-all ${activeTab === 'cta' ? 'bg-blue-500 text-white shadow-lg' : 'text-gray-400'}`}
        >
          <Video size={18} /> <span className="text-sm font-medium">CTA</span>
        </button>
      </div>

      <div className="glass-card p-6 min-h-[420px] relative overflow-hidden">
        <AnimatePresence mode="wait">
          {activeTab === 'branding' && (
            <motion.div
              key="branding"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              className="space-y-6"
            >
              <h3 className="text-lg font-semibold">Overlay Plate</h3>
              <p className="text-gray-400 text-sm">Upload your plate and preview how it overlays a video frame.</p>

              <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/webp"
                onChange={handlePlateSelected}
                className="hidden"
              />

              <button
                type="button"
                onClick={handlePickFile}
                disabled={uploadingPlate}
                className="w-full border-2 border-dashed border-gray-700 rounded-3xl p-8 flex flex-col items-center justify-center gap-4 bg-black/20 hover:border-blue-500/50 transition-colors cursor-pointer disabled:opacity-60"
              >
                <div className="bg-blue-500/20 p-4 rounded-full">
                  <Upload className="text-blue-500" />
                </div>
                <div className="text-center">
                  <p className="font-medium">{uploadingPlate ? 'Uploading...' : 'Click to upload plate'}</p>
                  <p className="text-xs text-gray-500 mt-1">PNG or WEBP, max 5MB</p>
                </div>
              </button>

              <div className="rounded-2xl overflow-hidden border border-gray-700">
                <div className="h-44 bg-gradient-to-br from-slate-700 via-slate-800 to-black relative">
                  <div className="absolute inset-0 opacity-30 bg-[radial-gradient(circle_at_center,_rgba(255,255,255,0.2)_0,_transparent_60%)]" />
                  <div className="absolute bottom-3 left-3 right-3 text-xs text-white/80 font-medium">
                    Video preview: plate placement simulation
                  </div>
                  {platePreviewUrl && (
                    <img
                      src={platePreviewUrl}
                      alt="Plate preview"
                      className="absolute right-4 top-4 max-h-16 max-w-[45%] object-contain"
                    />
                  )}
                </div>
              </div>

              <div className="text-xs text-gray-400">
                {plateFile ? `Selected file: ${plateFile.name}` : 'No plate selected yet.'}
              </div>
            </motion.div>
          )}

          {activeTab === 'subtitles' && (
            <motion.div
              key="subtitles"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              className="space-y-6"
            >
              <h3 className="text-lg font-semibold">Subtitles Design</h3>

              <div className="space-y-4">
                <div>
                  <label className="text-sm text-gray-400 mb-2 block">Font Family</label>
                  <select
                    value={font}
                    onChange={(e) => setFont(e.target.value)}
                    className="w-full input-field text-white"
                  >
                    <option>Montserrat</option>
                    <option>Inter</option>
                    <option>Bangers</option>
                    <option>Roboto</option>
                    <option>Outfit</option>
                  </select>
                </div>

                <div>
                  <div className="flex justify-between mb-2">
                    <label className="text-sm text-gray-400">Size</label>
                    <span className="text-sm font-mono text-blue-500">{fontSize}px</span>
                  </div>
                  <input
                    type="range"
                    min="20"
                    max="100"
                    value={fontSize}
                    onChange={(e) => setFontSize(parseInt(e.target.value, 10))}
                    className="w-full h-1 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
                  />
                </div>

                <div>
                  <label className="text-sm text-gray-400 mb-2 block">Font Color</label>
                  <input
                    type="color"
                    value={fontColor}
                    onChange={(e) => setFontColor(e.target.value)}
                    className="w-full h-10 rounded-lg bg-transparent border border-gray-700"
                  />
                </div>

                <div className="mt-8 p-6 rounded-2xl bg-black border border-gray-800 flex items-center justify-center min-h-[120px]">
                  <p style={{ fontFamily: font, fontSize: `${fontSize / 2}px`, color: fontColor }} className="text-center font-bold tracking-wide">
                    Subtitle style preview
                  </p>
                </div>
              </div>
            </motion.div>
          )}

          {activeTab === 'cta' && (
            <motion.div
              key="cta"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              className="space-y-4"
            >
              <h3 className="text-lg font-semibold">CTA Clips</h3>
              <p className="text-gray-400 text-sm">CTA upload UI is next in line. Branding and subtitle settings are ready now.</p>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {statusText && <div className="mt-4 text-sm text-gray-300">{statusText}</div>}

      <div className="fixed bottom-8 left-4 right-4">
        <button
          onClick={handleSave}
          disabled={loading}
          className="w-full btn-primary flex items-center justify-center gap-2 shadow-2xl shadow-blue-500/20 disabled:opacity-70"
        >
          {loading ? (
            <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
          ) : saved ? (
            <><Check size={20} /> Settings Saved</>
          ) : (
            <><Save size={20} /> Save Changes</>
          )}
        </button>
      </div>
    </div>
  );
};

export default App;
