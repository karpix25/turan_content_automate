import React, { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { CalendarClock, Loader2, Sparkles } from 'lucide-react';
import { apiClient } from '../../api/client';
import { useTelegram } from '../../context/TelegramContext';

export const PlanningTab: React.FC = () => {
  const { telegramId } = useTelegram();
  const [autoSchedule, setAutoSchedule] = useState(true);
  const [timeStart, setTimeStart] = useState('09:00');
  const [timeEnd, setTimeEnd] = useState('21:00');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const loadSettings = async () => {
      if (!telegramId) return;
      setLoading(true);
      try {
        const data = await apiClient.getSettings(telegramId);
        setAutoSchedule(data.auto_schedule_enabled);
        setTimeStart(data.publish_window_start_msk);
        setTimeEnd(data.publish_window_end_msk);
      } catch (error) {
      } finally {
        setLoading(false);
      }
    };
    loadSettings();
  }, [telegramId]);

  const saveSettings = async () => {
    if (!telegramId) return;
    setSaving(true);
    try {
      await apiClient.updateSettings(telegramId, {
        auto_schedule_enabled: autoSchedule,
        publish_window_start_msk: timeStart,
        publish_window_end_msk: timeEnd
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (error) {
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-10 gap-3 text-slate-400">
        <Loader2 className="animate-spin w-8 h-8" />
        <p className="text-sm font-medium">Загрузка настроек...</p>
      </div>
    );
  }

  return (
    <motion.div key="planning" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="space-y-4 pb-20">
      <div className="tg-card overflow-hidden">
        <div className="p-4 border-b border-slate-100 flex items-center gap-3 bg-gradient-to-r from-blue-50/50 to-transparent">
          <div className="w-10 h-10 rounded-xl bg-blue-100/50 flex items-center justify-center text-[#24a1de]">
            <Sparkles size={20} />
          </div>
          <div>
            <h3 className="text-[17px] font-bold text-slate-900 leading-tight">Авто-расписание</h3>
            <p className="text-xs text-slate-500 mt-0.5">Умное распределение публикаций</p>
          </div>
          <div className="ml-auto">
            <button
              onClick={() => setAutoSchedule(!autoSchedule)}
              className={`relative inline-flex h-7 w-12 items-center rounded-full transition-colors ${autoSchedule ? 'bg-[#34c759]' : 'bg-[#e9e9eb]'}`}
            >
              <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${autoSchedule ? 'translate-x-6' : 'translate-x-1'}`} />
            </button>
          </div>
        </div>

        <div className={`p-4 space-y-5 transition-opacity ${!autoSchedule ? 'opacity-50 pointer-events-none' : ''}`}>
          <div>
            <label className="text-xs font-bold text-[#707579] uppercase tracking-wider mb-2 block">
              Окно публикаций (МСК)
            </label>
            <div className="flex items-center gap-3">
              <div className="flex-1 relative">
                <input
                  type="time"
                  value={timeStart}
                  onChange={(e) => setTimeStart(e.target.value)}
                  className="input-field w-full h-11 pl-10 text-[15px] font-medium"
                />
                <CalendarClock size={16} className="absolute left-3 top-3.5 text-slate-400" />
              </div>
              <span className="text-slate-300 font-bold">—</span>
              <div className="flex-1 relative">
                <input
                  type="time"
                  value={timeEnd}
                  onChange={(e) => setTimeEnd(e.target.value)}
                  className="input-field w-full h-11 pl-10 text-[15px] font-medium"
                />
                <CalendarClock size={16} className="absolute left-3 top-3.5 text-slate-400" />
              </div>
            </div>
            <p className="text-[11px] text-slate-500 mt-2 leading-relaxed">
              Видео будут автоматически планироваться в случайное время внутри этого окна. 
              Интервал между публикациями рассчитывается автоматически.
            </p>
          </div>
        </div>
      </div>

      <button
        onClick={saveSettings}
        disabled={saving}
        className={`w-full h-12 text-[15px] font-bold rounded-xl flex items-center justify-center gap-2 shadow-lg transition-all ${
          saved ? 'bg-[#34c759] text-white shadow-green-500/20' : 'bg-[#24a1de] text-white shadow-blue-500/20'
        } disabled:opacity-50`}
      >
        {saving ? <Loader2 className="animate-spin" size={20} /> : null}
        {saved ? 'Настройки сохранены' : 'Сохранить параметры'}
      </button>
    </motion.div>
  );
};
