export type UserSettings = {
  auto_schedule_enabled: boolean;
  publish_limit_per_day: number;
  publish_window_start_msk: string;
  publish_window_end_msk: string;
  selected_plate_id?: number | null;
  plate_start_percent?: number;
  author_style_profile?: string | null;
  training_source?: string | null;
  heygen_avatar_id?: string | null;
  elevenlabs_voice_id?: string | null;
  thumbnail_face_path?: string | null;
  avatar_insert_start_percent?: number;
  avatar_insert_end_percent?: number;
  avatar_insert_clips_count?: number;
  youtube_description_template?: string | null;
};

export type VideoTaskItem = {
  id: number;
  source_url: string;
  source_title?: string | null;
  type: string;
  status: string;
  output_path?: string | null;
  target_account_id?: number | null;
  target_platform?: string | null;
  preview_url?: string | null;
  publish_at?: string | null;
  publishing_status: string;
  created_at: string;
  updated_at: string;
};

export type PlateAsset = {
  id: number;
  file_path: string;
};

export type PublishAccount = {
  account_id: number;
  account_name: string;
  account_login?: string | null;
  channel_id?: number | null;
  channel_code?: string | null;
  channel_name?: string | null;
  enabled: boolean;
  description?: string | null;
  selected_plate_id?: number | null;
  selected_plate_ids?: number[];
  plate_start_percent?: number | null;
  plate_file_path?: string | null;
  plate_assets?: PlateAsset[];
};

export type EndingClip = {
  id: number;
  user_id: number;
  account_id?: number | null;
  file_path: string;
  label?: string | null;
  platform: string;
};

export type ThumbnailReference = {
  id: number;
  user_id: number;
  file_path: string;
  created_at: string;
};

export type AvatarInsertClip = {
  id: number;
  user_id: number;
  file_path: string;
  created_at: string;
};

export type TelegramWebApp = {
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
