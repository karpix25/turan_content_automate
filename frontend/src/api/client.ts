import axios from 'axios';
import { UserSettings, VideoTaskItem, PublishAccount, EndingClip, ThumbnailReference, AvatarInsertClip } from '../types';

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
      elevenlabs_voice_speeds: Record<string, {
        chars_per_second?: number;
        demo_char_count?: number;
        demo_duration_seconds?: number;
      }> | null;
      thumbnail_face_path: string | null;
      vertical_thumbnail_face_path: string | null;
      avatar_script_duration_minutes: number;
      avatar_insert_start_percent: number;
      avatar_insert_end_percent: number;
      avatar_insert_clips_count: number;
      reels_broll_yandex_dir: string;
      reels_broll_start_percent: number;
      reels_broll_end_percent: number;
      reels_broll_clips_count: number;
      reels_broll_coverage_percent: number;
      youtube_description_template: string | null;
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
  getTasks: async (telegramId: string, filters?: { publish_from?: string; publish_to?: string }) => {
    const res = await axios.get<VideoTaskItem[]>(`${API_BASE}/tasks/${telegramId}`, {
      params: filters
    });
    return res.data;
  },
  createTask: async (telegramId: string, payload: { source_url: string; type: string; publish_at?: string }) => {
    const res = await axios.post(`${API_BASE}/tasks/${telegramId}`, payload);
    return res.data;
  },
  updateTaskSchedule: async (telegramId: string, taskId: number, publishAt: string | null) => {
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

  // Thumbnail references / face
  listThumbnailReferences: async (telegramId: string) => {
    const res = await axios.get<ThumbnailReference[]>(`${API_BASE}/thumbnail-references/${telegramId}`);
    return res.data;
  },
  listVerticalThumbnailReferences: async (telegramId: string) => {
    const res = await axios.get<ThumbnailReference[]>(`${API_BASE}/vertical-thumbnail-references/${telegramId}`);
    return res.data;
  },
  uploadThumbnailReference: async (telegramId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await axios.post<ThumbnailReference>(`${API_BASE}/upload/thumbnail-reference/${telegramId}`, formData);
    return res.data;
  },
  uploadVerticalThumbnailReference: async (telegramId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await axios.post<ThumbnailReference>(`${API_BASE}/upload/vertical-thumbnail-reference/${telegramId}`, formData);
    return res.data;
  },
  deleteThumbnailReference: async (telegramId: string, referenceId: number) => {
    const res = await axios.delete(`${API_BASE}/thumbnail-references/${telegramId}/${referenceId}`);
    return res.data;
  },
  uploadThumbnailFace: async (telegramId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await axios.post<{ status: string; file_path: string }>(`${API_BASE}/upload/thumbnail-face/${telegramId}`, formData);
    return res.data;
  },
  deleteThumbnailFace: async (telegramId: string) => {
    const res = await axios.delete(`${API_BASE}/thumbnail-face/${telegramId}`);
    return res.data;
  },
  uploadVerticalThumbnailFace: async (telegramId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await axios.post<{ status: string; file_path: string }>(`${API_BASE}/upload/vertical-thumbnail-face/${telegramId}`, formData);
    return res.data;
  },
  deleteVerticalThumbnailFace: async (telegramId: string) => {
    const res = await axios.delete(`${API_BASE}/vertical-thumbnail-face/${telegramId}`);
    return res.data;
  },
  listAvatarInsertClips: async (telegramId: string) => {
    const res = await axios.get<AvatarInsertClip[]>(`${API_BASE}/avatar-inserts/${telegramId}`);
    return res.data;
  },
  uploadAvatarInsertClip: async (telegramId: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await axios.post<AvatarInsertClip>(`${API_BASE}/upload/avatar-insert/${telegramId}`, formData);
    return res.data;
  },
  uploadAvatarInsertClips: async (telegramId: string, files: File[]) => {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));
    const res = await axios.post<AvatarInsertClip[]>(`${API_BASE}/upload/avatar-inserts/${telegramId}`, formData);
    return res.data;
  },
  deleteAvatarInsertClip: async (telegramId: string, clipId: number) => {
    const res = await axios.delete(`${API_BASE}/avatar-inserts/${telegramId}/${clipId}`);
    return res.data;
  },
};
