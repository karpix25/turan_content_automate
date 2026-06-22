import axios from 'axios';

export const getApiErrorMessage = (error: unknown, fallback: string) => {
  if (!axios.isAxiosError(error)) return fallback;
  const status = error.response?.status;
  const detail = error.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (status === 413) return 'Файл слишком большой для загрузки.';
  if (status === 400) return 'Файл не принят сервером. Проверь формат и размер.';
  if (status === 502) return 'Сервер не успел обработать загрузку. Попробуй файл меньшего размера или повтори позже.';
  return fallback;
};
