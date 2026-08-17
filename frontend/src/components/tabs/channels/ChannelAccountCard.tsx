import React from 'react';
import { ChevronDown, Film, Loader2, Trash2, Upload } from 'lucide-react';
import { EndingClip, PublishAccount } from '../../../types';

type ChannelAccountCardProps = {
  account: PublishAccount;
  accountEndings: EndingClip[];
  isCollapsed: boolean;
  isSaving: boolean;
  isUploadingPlate: boolean;
  isUploadingEnding: boolean;
  deletingPlateId: number | null;
  deletingEndingId: number | null;
  description: string;
  plateStartPercent: number;
  getMediaUrl: (path: string) => string;
  onToggleEnabled: (accountId: number) => void;
  onToggleCollapse: (accountId: number) => void;
  onDescriptionChange: (accountId: number, value: string) => void;
  onPlateStartPercentChange: (accountId: number, value: number) => void;
  onUploadPlate: (account: PublishAccount) => void;
  onUploadEnding: (account: PublishAccount) => void;
  onDeletePlate: (plateId: number) => void;
  onDeleteEnding: (endingId: number) => void;
};

export const ChannelAccountCard: React.FC<ChannelAccountCardProps> = ({
  account,
  accountEndings,
  isCollapsed,
  isSaving,
  isUploadingPlate,
  isUploadingEnding,
  deletingPlateId,
  deletingEndingId,
  description,
  plateStartPercent,
  getMediaUrl,
  onToggleEnabled,
  onToggleCollapse,
  onDescriptionChange,
  onPlateStartPercentChange,
  onUploadPlate,
  onUploadEnding,
  onDeletePlate,
  onDeleteEnding,
}) => (
  <div className={`tg-card overflow-hidden transition-opacity ${!account.enabled ? 'opacity-60' : ''}`}>
    <div className="p-4">
      <div className="flex items-start justify-between gap-4 mb-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <button
              onClick={() => onToggleCollapse(account.account_id)}
              className="h-8 w-8 -ml-1 rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-900 flex items-center justify-center transition-colors"
              aria-label={isCollapsed ? 'Развернуть канал' : 'Свернуть канал'}
            >
              <ChevronDown
                size={18}
                className={`transition-transform ${isCollapsed ? '-rotate-90' : 'rotate-0'}`}
              />
            </button>
            <h4 className="text-[17px] font-bold text-slate-900 leading-tight truncate">
              {account.account_name}
            </h4>
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Канал: {account.channel_name || 'Неизвестно'} <span className="opacity-50">({account.channel_code})</span>
          </p>
        </div>
        <button
          onClick={() => onToggleEnabled(account.account_id)}
          disabled={isSaving}
          className={`relative inline-flex h-7 w-12 items-center rounded-full transition-colors shrink-0 ${account.enabled ? 'bg-[#34c759]' : 'bg-[#e9e9eb]'}`}
        >
          <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${account.enabled ? 'translate-x-6' : 'translate-x-1'}`} />
        </button>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <span className={`px-2 py-1 rounded-lg text-[10px] font-bold ${account.description ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
          Описание {account.description ? 'есть' : 'нет'}
        </span>
        <span className={`px-2 py-1 rounded-lg text-[10px] font-bold ${(account.plate_assets || []).length > 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
          Плашки {(account.plate_assets || []).length}
        </span>
        <span className={`px-2 py-1 rounded-lg text-[10px] font-bold ${accountEndings.length > 0 ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
          Концовки {accountEndings.length}
        </span>
      </div>

      {account.enabled && !isCollapsed && (
        <div className="mt-4 space-y-4 pt-4 border-t border-slate-100">
          <div>
            <label className="text-xs font-bold text-[#707579] uppercase tracking-wider mb-2 block">Описание (шаблон поста)</label>
            <textarea
              value={description}
              onChange={(e) => onDescriptionChange(account.account_id, e.target.value)}
              placeholder="Введите текст, который будет добавляться к каждому посту..."
              className="input-field text-sm min-h-[80px] leading-relaxed resize-y"
            />
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-slate-50 rounded-xl p-3 border border-slate-100">
              <div className="flex items-center justify-between mb-3">
                <label className="text-xs font-bold text-[#707579] uppercase tracking-wider">Плашки</label>
                <button
                  onClick={() => onUploadPlate(account)}
                  disabled={isUploadingPlate}
                  className="text-[#24a1de] hover:bg-blue-50 p-1.5 rounded-lg transition-colors disabled:opacity-50"
                >
                  {isUploadingPlate ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
                </button>
              </div>

              <div className="space-y-2 mb-3">
                {account.plate_assets?.map(plate => {
                  const isVideoPlate = plate.media_type === 'video';
                  return (
                    <div key={plate.id} className="flex items-center gap-2 bg-white p-1.5 rounded-lg border border-slate-100">
                      {isVideoPlate ? (
                        <video src={getMediaUrl(plate.file_path)} muted playsInline className="w-8 h-8 object-cover rounded bg-slate-100" />
                      ) : (
                        <img src={getMediaUrl(plate.file_path)} alt="Plate" className="w-8 h-8 object-cover rounded bg-slate-100" />
                      )}
                      <span className="text-[10px] text-slate-500 flex-1 truncate">{plate.file_path.split('/').pop()}</span>
                      {isVideoPlate && (
                        <span className="h-6 w-6 rounded-md bg-blue-50 text-[#24a1de] flex items-center justify-center" title="Видео-плашка">
                          <Film size={13} />
                        </span>
                      )}
                      <button
                        onClick={() => onDeletePlate(plate.id)}
                        disabled={deletingPlateId === plate.id}
                        className="p-1.5 text-slate-400 hover:text-rose-500 rounded-md"
                      >
                        {deletingPlateId === plate.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                      </button>
                    </div>
                  );
                })}
                {(!account.plate_assets || account.plate_assets.length === 0) && (
                  <p className="text-xs text-slate-400 italic">Нет загруженных плашек</p>
                )}
              </div>

              <div className="flex items-center gap-2">
                <span className="text-[10px] font-medium text-slate-500 whitespace-nowrap">Время (%):</span>
                <input
                  type="number"
                  min="0"
                  max="100"
                  value={plateStartPercent}
                  onChange={(e) => onPlateStartPercentChange(account.account_id, Number(e.target.value))}
                  className="input-field h-7 text-xs px-2"
                />
              </div>
            </div>

            <div className="bg-slate-50 rounded-xl p-3 border border-slate-100">
              <div className="flex items-center justify-between mb-3">
                <label className="text-xs font-bold text-[#707579] uppercase tracking-wider">Концовки</label>
                <button
                  onClick={() => onUploadEnding(account)}
                  disabled={isUploadingEnding}
                  className="text-[#24a1de] hover:bg-blue-50 p-1.5 rounded-lg transition-colors disabled:opacity-50"
                >
                  {isUploadingEnding ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
                </button>
              </div>

              <div className="space-y-2">
                {accountEndings.map(ending => (
                  <div key={ending.id} className="flex items-center gap-2 bg-white p-1.5 rounded-lg border border-slate-100">
                    <div className="w-8 h-8 rounded bg-slate-100 overflow-hidden flex-shrink-0">
                      {ending.file_path.toLowerCase().endsWith('.mp4') ? (
                        <video src={getMediaUrl(ending.file_path)} className="w-full h-full object-cover" />
                      ) : (
                        <img src={getMediaUrl(ending.file_path)} className="w-full h-full object-cover" />
                      )}
                    </div>
                    <span className="text-[10px] font-bold bg-slate-100 px-1.5 py-0.5 rounded text-slate-500 uppercase">
                      {ending.platform}
                    </span>
                    <span className="text-[10px] text-slate-500 flex-1 truncate">{ending.file_path.split('/').pop()}</span>
                    <button
                      onClick={() => onDeleteEnding(ending.id)}
                      disabled={deletingEndingId === ending.id}
                      className="p-1.5 text-slate-400 hover:text-rose-500 rounded-md"
                    >
                      {deletingEndingId === ending.id ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />}
                    </button>
                  </div>
                ))}
                {accountEndings.length === 0 && (
                  <p className="text-xs text-slate-400 italic">Нет загруженных концовок</p>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  </div>
);
