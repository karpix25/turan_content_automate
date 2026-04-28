import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';

const TELEGRAM_ID_STORAGE_KEY = 'content_studio_telegram_id';

const normalizeTelegramId = (value: unknown): string => {
  const text = String(value ?? '').trim();
  return /^\d{5,20}$/.test(text) ? text : '';
};

const getTelegramIdFromInitDataHash = (): string => {
  const hash = String(window.location.hash || '').replace(/^#/, '');
  if (!hash) return '';

  const webAppParams = new URLSearchParams(hash);
  const rawInitData = webAppParams.get('tgWebAppData');
  if (!rawInitData) return '';

  try {
    const initData = new URLSearchParams(rawInitData);
    const rawUser = initData.get('user');
    if (!rawUser) return '';

    const user = JSON.parse(rawUser) as { id?: number | string };
    return normalizeTelegramId(user?.id);
  } catch {
    return '';
  }
};

type TelegramContextType = {
  telegramId: string;
  telegramIdInput: string;
  setTelegramIdInput: (id: string) => void;
  applyTelegramId: () => void;
};

const TelegramContext = createContext<TelegramContextType | undefined>(undefined);

export const TelegramProvider = ({ children }: { children: ReactNode }) => {
  const [telegramId, setTelegramId] = useState('');
  const [telegramIdInput, setTelegramIdInput] = useState('');

  useEffect(() => {
    const tg = window.Telegram?.WebApp;
    if (tg?.ready) tg.ready();
    if (tg?.expand) tg.expand();

    const storedId = window.localStorage.getItem(TELEGRAM_ID_STORAGE_KEY) || '';
    const tgIdFromHash = getTelegramIdFromInitDataHash();
    const rawTgIdFromUnsafe = tg?.initDataUnsafe?.user?.id;
    const tgIdFromUnsafe = normalizeTelegramId(rawTgIdFromUnsafe);

    let initialId = tgIdFromUnsafe || tgIdFromHash;
    if (!initialId && storedId) {
      initialId = storedId;
    }

    if (initialId) {
      setTelegramId(initialId);
      setTelegramIdInput(initialId);
      window.localStorage.setItem(TELEGRAM_ID_STORAGE_KEY, initialId);
    }
  }, []);

  const applyTelegramId = () => {
    const nextId = normalizeTelegramId(telegramIdInput);
    if (!nextId) {
      setTelegramId('');
      setTelegramIdInput('');
      window.localStorage.removeItem(TELEGRAM_ID_STORAGE_KEY);
      return;
    }
    setTelegramId(nextId);
    setTelegramIdInput(nextId);
    window.localStorage.setItem(TELEGRAM_ID_STORAGE_KEY, nextId);
  };

  return (
    <TelegramContext.Provider value={{ telegramId, telegramIdInput, setTelegramIdInput, applyTelegramId }}>
      {children}
    </TelegramContext.Provider>
  );
};

export const useTelegram = () => {
  const context = useContext(TelegramContext);
  if (context === undefined) {
    throw new Error('useTelegram must be used within a TelegramProvider');
  }
  return context;
};
