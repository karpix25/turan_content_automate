export type UserSettings = {
  auto_schedule_enabled: boolean;
  publish_limit_per_day: number;
  publish_window_start_msk: string;
  publish_window_end_msk: string;
  selected_plate_id?: number | null;
  plate_start_percent?: number;
  author_style_profile?: string | null;
  training_source?: string | null;
  style_training_status?: string | null;
  style_training_error?: string | null;
  style_training_updated_at?: string | null;
  heygen_avatar_id?: string | null;
  heygen_vertical_avatar_id?: string | null;
  heygen_video_api_version?: 'v2' | 'v3';
  heygen_avatar_engine?: 'avatar_iv' | 'avatar_v';
  elevenlabs_voice_id?: string | null;
  elevenlabs_voice_speeds?: Record<string, {
    chars_per_second?: number;
    demo_char_count?: number;
    demo_duration_seconds?: number;
  }> | null;
  thumbnail_face_path?: string | null;
  vertical_thumbnail_face_path?: string | null;
  avatar_script_duration_minutes?: number;
  avatar_vertical_duration_seconds?: number;
  avatar_insert_start_percent?: number;
  avatar_insert_end_percent?: number;
  avatar_insert_clips_count?: number;
  avatar_overlay_x_percent?: number;
  avatar_overlay_y_percent?: number;
  avatar_overlay_size_percent?: number;
  avatar_overlay_opacity_percent?: number;
  reels_broll_yandex_dir?: string;
  reels_broll_start_percent?: number;
  reels_broll_end_percent?: number;
  reels_broll_clips_count?: number;
  reels_broll_coverage_percent?: number;
  youtube_description_template?: string | null;
  instagram_post_5s_audio_profile?: string | null;
  instagram_post_5s_audio_status?: string | null;
  instagram_post_5s_audio_error?: string | null;
  instagram_post_5s_audio_refreshed_at?: string | null;
  instagram_post_5s_overlay_path?: string | null;
  instagram_post_5s_cta_text?: string | null;
  instagram_post_5s_image_prompt?: string | null;
};

export type VideoTaskItem = {
  id: number;
  source_url: string;
  source_title?: string | null;
  type: string;
  status: string;
  output_path?: string | null;
  postmypost_project_id?: number | null;
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
  postmypost_project_id?: number | null;
  account_id?: number | null;
  media_type?: 'image' | 'video';
};

export type BrollAsset = {
  id: number;
  postmypost_project_id: number;
  file_path: string;
  original_filename: string;
  is_active: boolean;
  created_at: string;
};

export type UniqueizationMode = 'auto' | 'light' | 'standard' | 'aggressive' | 'off';

export type PublishAccount = {
  account_id: number;
  account_name: string;
  account_login?: string | null;
  channel_id?: number | null;
  channel_code?: string | null;
  channel_name?: string | null;
  enabled: boolean;
  description?: string | null;
  publish_limit_per_day?: number;
  selected_plate_id?: number | null;
  selected_plate_ids?: number[];
  plate_start_percent?: number | null;
  plate_file_path?: string | null;
  plate_assets?: PlateAsset[];
};

export type PostMyPostProject = {
  id: number;
  name: string;
  timezone_id?: number | null;
  selected: boolean;
  uniqueization_mode?: UniqueizationMode | null;
};

export type PostMyPostProjectsResponse = {
  selected_project_id?: number | null;
  selected_project_uniqueization_mode?: UniqueizationMode | null;
  projects: PostMyPostProject[];
};

export type EndingClip = {
  id: number;
  user_id: number;
  postmypost_project_id?: number | null;
  account_id?: number | null;
  file_path: string;
  label?: string | null;
  platform: string;
};

export type ThumbnailReference = {
  id: number;
  user_id: number;
  file_path: string;
  kind?: string;
  created_at: string;
};

export type ThumbnailFaceReference = {
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

export type InstagramPost5sAudioTrack = {
  id: number;
  user_id: number;
  source_profile?: string | null;
  source_url?: string | null;
  source_code?: string | null;
  file_path: string;
  created_at: string;
};

export type InstagramPost5sSettings = {
  audio_profile?: string | null;
  audio_status?: string | null;
  audio_error?: string | null;
  audio_refreshed_at?: string | null;
  overlay_path?: string | null;
  cta_text?: string | null;
  image_prompt?: string | null;
  audio_tracks: InstagramPost5sAudioTrack[];
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
