import axios from 'axios';
import { UserSettings, VideoTaskItem, PublishAccount, EndingClip } from '../types';

const API_BASE = import.meta.env.VITE_API_BASE || '/api';

export const apiClient = {
  // Settings
  getSettings: async (telegramId: string) => {
    const res = await axios.get<UserSettings>(`${API_BASE}/settings/${telegramId}`);
    return res.data;
  },
  getStyleSettings: async (telegramId: string) => {
    const res = await axios.get<{
      author_style_profile: string | null;
      training_source: string | null;
      heygen_avatar_id: string | null;
      elevenlabs_voice_id: string | null;
    }>(`${API_BASE}/settings/style/${telegramId}`);
    return res.data;
  },
  updateSettings: async (telegramId: string, data: Partial<UserSettings>) => {
    const res = await axios.post(`${API_BASE}/settings/${telegramId}/update`, data);
    return res.data;
  },
  trainStyle: async (telegramId: string, channelUrl: string, videoCount: number) => {
    const res = await axios.post(`${API_BASE}/settings/train-style/${telegramId}`, {
      channel_url: channelUrl,
      video_count: videoCount,
    });
    return res.data;
  },
  getElevenLabsVoices: async (telegramId: string) => {
    const res = await axios.get(`${API_BASE}/elevenlabs/voices`, {
      params: { telegram_id: telegramId }
    });
    return res.data;
  },
  getHeyGenAvatars: async (telegramId: string) => {
    const res = await axios.get(`${API_BASE}/heygen/avatars`, {
      params: { telegram_id: telegramId }
    });
    return res.data;
  },

  // Tasks
  getTasks: async (telegramId: string) => {
    const res = await axios.get<VideoTaskItem[]>(`${API_BASE}/tasks/${telegramId}`);
    return res.data;
  },
  createTask: async (telegramId: string, payload: { source_url: string; type: string; publish_at?: string }) => {
    const res = await axios.post(`${API_BASE}/tasks/${telegramId}`, payload);
    return res.data;
  },
  updateTaskSchedule: async (telegramId: string, taskId: number, publishAt: string) => {
    const res = await axios.patch(`${API_BASE}/tasks/${telegramId}/${taskId}/schedule`, { publish_at: publishAt });
    return res.data;
  },
  publishTaskNow: async (telegramId: string, taskId: number) => {
    const res = await axios.post(`${API_BASE}/tasks/${telegramId}/${taskId}/publish-now`);
    return res.data;
  },
  deleteTask: async (telegramId: string, taskId: number) => {
    const res = await axios.delete(`${API_BASE}/tasks/${telegramId}/${taskId}`);
    return res.data;
  },

  // Channels
  getChannels: async (telegramId: string) => {
    const res = await axios.get<PublishAccount[]>(`${API_BASE}/postmypost/channels/${telegramId}`);
    return res.data;
  },
  updateChannels: async (telegramId: string, payload: any) => {
    const res = await axios.post<PublishAccount[]>(`${API_BASE}/postmypost/channels/${telegramId}`, payload);
    return res.data;
  },

  // Endings & Plates
  getEndings: async (telegramId: string) => {
    const res = await axios.get<EndingClip[]>(`${API_BASE}/endings/${telegramId}`);
    return res.data;
  },
  deletePlate: async (telegramId: string, plateId: number) => {
    const res = await axios.delete(`${API_BASE}/plates/${telegramId}/${plateId}`);
    return res.data;
  },
  deleteEnding: async (telegramId: string, endingId: number) => {
    const res = await axios.delete(`${API_BASE}/endings/${telegramId}/${endingId}`);
    return res.data;
  },
};
