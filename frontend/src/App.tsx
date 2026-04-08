import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Settings, Image as ImageIcon, Video, Type, Save, Check, Upload } from 'lucide-react';
import axios from 'axios';

const App = () => {
  const [activeTab, setActiveTab] = useState('branding');
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);
  
  // Settings State
  const [font, setFont] = useState('Montserrat');
  const [fontSize, setFontSize] = useState(60);
  const [fontColor, setFontColor] = useState('#FFFFFF');
  const [plate, setPlate] = useState<File | null>(null);
  
  // Publication State
  const [isScheduled, setIsScheduled] = useState(false);
  const [publishAt, setPublishAt] = useState('');

  const telegram_id = "12345678"; // This would be fetched from window.Telegram.WebApp

  const handleSave = async () => {
    setLoading(true);
    // Mimic API call
    setTimeout(() => {
      setLoading(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    }, 1500);
  };

  return (
    <div className="min-h-screen p-4 max-w-md mx-auto">
      {/* Header */}
      <header className="flex justify-between items-center mb-8 pt-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Content Studio</h1>
          <p className="text-gray-400 text-sm">Customize your social clips</p>
        </div>
        <div className="bg-blue-500/10 p-2 rounded-full">
          <Settings className="text-blue-500" size={20} />
        </div>
      </header>

      {/* Tabs */}
      <div className="flex bg-secondary rounded-2xl p-1 mb-6">
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

      {/* Content */}
      <div className="glass-card p-6 min-h-[400px] relative overflow-hidden">
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
              <p className="text-gray-400 text-sm">Upload a PNG logo or branding plate to overlay on all your videos.</p>
              
              <div className="border-2 border-dashed border-gray-700 rounded-3xl p-8 flex flex-col items-center justify-center gap-4 bg-black/20 hover:border-blue-500/50 transition-colors cursor-pointer">
                <div className="bg-blue-500/20 p-4 rounded-full">
                  <Upload className="text-blue-500" />
                </div>
                <div className="text-center">
                  <p className="font-medium">Click to upload</p>
                  <p className="text-xs text-gray-500 mt-1">Supports PNG, WEBP (Max 5MB)</p>
                </div>
              </div>

              {/* Publication Timing Section */}
              <div className="mt-10 pt-6 border-t border-gray-800">
                <h4 className="text-sm font-semibold mb-4 text-gray-300">Publication Timing</h4>
                <div className="flex items-center justify-between mb-4">
                  <span className="text-sm">Schedule Post</span>
                  <button 
                    onClick={() => setIsScheduled(!isScheduled)}
                    className={`w-12 h-6 rounded-full p-1 transition-colors ${isScheduled ? 'bg-blue-500' : 'bg-gray-700'}`}
                  >
                    <div className={`w-4 h-4 bg-white rounded-full transition-transform ${isScheduled ? 'translate-x-6' : 'translate-x-0'}`} />
                  </button>
                </div>
                
                {isScheduled && (
                  <motion.div 
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    className="space-y-4"
                  >
                    <input 
                      type="datetime-local" 
                      value={publishAt}
                      onChange={(e) => setPublishAt(e.target.value)}
                      className="w-full input-field text-white color-scheme-dark"
                    />
                    <p className="text-xs text-gray-500">Video will be published via PostMyPost at this time.</p>
                  </motion.div>
                )}
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
                    onChange={(e) => setFontSize(parseInt(e.target.value))}
                    className="w-full h-1 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-blue-500"
                  />
                </div>

                {/* Preview Box */}
                <div className="mt-8 p-6 rounded-2xl bg-black border border-gray-800 flex items-center justify-center min-h-[120px]">
                   <p style={{ fontFamily: font, fontSize: `${fontSize/2}px`, color: fontColor }} className="text-center font-bold tracking-wide">
                     This is how your subtitles will look!
                   </p>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Floating Action Button */}
      <div className="fixed bottom-8 left-4 right-4">
        <button 
          onClick={handleSave}
          disabled={loading}
          className="w-full btn-primary flex items-center justify-center gap-2 shadow-2xl shadow-blue-500/20"
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
