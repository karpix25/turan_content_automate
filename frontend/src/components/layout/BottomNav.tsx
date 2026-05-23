import React from 'react';
import { CalendarClock, Settings, RefreshCcw, Globe2 } from 'lucide-react';

type BottomNavProps = {
  activeTab: string;
  setActiveTab: (tab: string) => void;
};

const ACTIVE_TAB_STORAGE_KEY = 'content_studio_active_tab';

export const BottomNav: React.FC<BottomNavProps> = ({ activeTab, setActiveTab }) => {
  const tabs = [
    { id: 'queue', icon: RefreshCcw, label: 'Очередь' },
    { id: 'channels', icon: Globe2, label: 'Каналы' },
    { id: 'planning', icon: CalendarClock, label: 'План' },
    { id: 'style', icon: Settings, label: 'Настройки' }
  ];

  const handleTabClick = (id: string) => {
    setActiveTab(id);
    window.localStorage.setItem(ACTIVE_TAB_STORAGE_KEY, id);
  };

  return (
    <nav className="bottom-nav">
      {tabs.map(tab => (
        <button 
          key={tab.id}
          onClick={() => handleTabClick(tab.id)}
          className={`nav-item ${activeTab === tab.id ? 'active' : ''}`}
        >
          <tab.icon size={22} />
          <span className="nav-label">{tab.label}</span>
        </button>
      ))}
    </nav>
  );
};
