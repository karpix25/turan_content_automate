import React, { useState, useEffect } from 'react';
import { AnimatePresence } from 'framer-motion';
import { Rocket } from 'lucide-react';

import { useTelegram } from './context/TelegramContext';
import { BottomNav } from './components/layout/BottomNav';
import { ProjectSwitcherBar } from './components/layout/ProjectSwitcherBar';
import { QueueTab } from './components/tabs/QueueTab';
import { ChannelsTab } from './components/tabs/ChannelsTab';
import { PlanningTab } from './components/tabs/PlanningTab';
import { SettingsTab } from './components/tabs/SettingsTab';

const ACTIVE_TAB_STORAGE_KEY = 'content_studio_active_tab';
const TAB_TITLES: Record<string, string> = {
  queue: 'Очередь',
  channels: 'Каналы',
  planning: 'План',
  style: 'Настройки',
};

const App: React.FC = () => {
  const { telegramId, telegramIdInput, setTelegramIdInput, applyTelegramId } = useTelegram();
  const [activeTab, setActiveTab] = useState('queue');

  useEffect(() => {
    const storedTab = window.localStorage.getItem(ACTIVE_TAB_STORAGE_KEY);
    if (storedTab && ['queue', 'channels', 'planning', 'style'].includes(storedTab)) {
      setActiveTab(storedTab);
    }
  }, []);

  if (!telegramId) {
    return (
      <div className="min-h-screen bg-[#f1f2f6] flex items-center justify-center p-4 font-sans">
        <div className="tg-card p-6 w-full max-w-sm">
          <div className="w-16 h-16 bg-[#24a1de] rounded-2xl flex items-center justify-center mx-auto mb-6 shadow-lg shadow-blue-500/30">
            <Rocket size={32} className="text-white" />
          </div>
          <h2 className="text-xl font-bold text-slate-900 text-center mb-2">Вход в систему</h2>
          <p className="text-sm text-slate-500 text-center mb-6">
            Откройте приложение через Telegram бота или введите свой ID вручную.
          </p>
          <div className="space-y-4">
            <div>
              <label className="text-xs font-bold text-[#707579] uppercase tracking-wider mb-2 block">
                Ваш Telegram ID
              </label>
              <input
                type="text"
                placeholder="Например: 123456789"
                value={telegramIdInput}
                onChange={(e) => setTelegramIdInput(e.target.value)}
                className="input-field w-full h-12 text-[15px] font-medium"
              />
            </div>
            <button
              onClick={applyTelegramId}
              disabled={!telegramIdInput.trim()}
              className="w-full h-12 bg-[#24a1de] text-white text-[15px] font-bold rounded-xl flex items-center justify-center shadow-lg shadow-blue-500/20 disabled:opacity-50"
            >
              Войти
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#f1f2f6] text-slate-900 font-sans app-container max-w-2xl mx-auto relative shadow-2xl">
      <header className="sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-slate-100 px-4 py-2.5 flex items-center justify-between shadow-sm">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-gradient-to-br from-[#24a1de] to-sky-400 rounded-xl flex items-center justify-center shadow-md shadow-blue-500/20">
            <Rocket size={18} className="text-white" />
          </div>
          <div>
            <h1 className="text-[16px] font-bold tracking-tight text-slate-900 leading-none">{TAB_TITLES[activeTab] || 'Content Studio'}</h1>
            <p className="text-[10px] font-medium text-slate-500 mt-0.5">Content Studio</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 px-2.5 py-1.5 bg-slate-100 rounded-lg">
            <div className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse"></div>
            <span className="text-[10px] font-bold text-slate-600 uppercase tracking-wider">Online</span>
          </div>
          <button 
            onClick={() => {
              if (window.confirm('Выйти из аккаунта?')) {
                setTelegramIdInput('');
                applyTelegramId();
              }
            }}
            className="text-[10px] font-bold text-slate-400 hover:text-rose-500 uppercase px-2 py-1.5 rounded-lg hover:bg-rose-50 transition-colors"
          >
            Выход
          </button>
        </div>
      </header>
      <ProjectSwitcherBar />

      <main className="p-4">
        <AnimatePresence mode="wait">
          {activeTab === 'queue' && <QueueTab />}
          {activeTab === 'channels' && <ChannelsTab />}
          {activeTab === 'planning' && <PlanningTab />}
          {activeTab === 'style' && <SettingsTab />}
        </AnimatePresence>
      </main>

      <BottomNav activeTab={activeTab} setActiveTab={setActiveTab} />
    </div>
  );
};

export default App;
