/**
 * 📦 보관함 다이얼로그
 *
 * 소유한 캐릭터와 배경을 관리하는 팝업
 * - 현재 적용 중인 아이템에 체크 표시
 * - 캐릭터: 레벨 표시
 * - 다른 아이템 선택 시 확인 팝업
 */

import { useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Check, UserRound, Palette } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import { CHARACTERS, BACKGROUNDS } from './gameData';
import { gameApi } from '@/services/api';
import { toast } from 'sonner';
import { createPortal } from 'react-dom';


interface StorageDialogProps {
  open: boolean;
  onClose: () => void;
}

type StorageTab = 'character' | 'background';

const StorageDialog = ({ open, onClose }: StorageDialogProps) => {
  const {
    selectedCharacter,
    selectedBackground,
    ownedCharacters,
    ownedBackgroundIds,
    level,
    syncGameProfile,
    refreshGameState,
  } = useAppStore();

  const [activeTab, setActiveTab] = useState<StorageTab>('character');
  const [confirmItem, setConfirmItem] = useState<{ id: string; type: StorageTab; name: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const displayCharacters = useMemo(() => {
    const ownedIds = ownedCharacters.map(oc => oc.id); 
    
    return CHARACTERS.filter(
      (c) => ownedIds.includes(c.id) || c.price === 0
    );
  }, [ownedCharacters]);

  const ownedBackgrounds = useMemo(
    () => BACKGROUNDS.filter((b) => ownedBackgroundIds.includes(b.id) || b.price === 0),
    [ownedBackgroundIds]
  );

  const handleSelect = (id: string, type: StorageTab, name: string) => {
    if (type === 'character' && id === selectedCharacter) return;
    if (type === 'background' && id === selectedBackground) return;
    setConfirmItem({ id, type, name });
  };

  const handleConfirm = async () => {
    if (!confirmItem || submitting) return;

    try {
      setSubmitting(true);
      let response;

      if (confirmItem.type === 'character') {
        response = await gameApi.equipCharacter({ character_id: confirmItem.id });
      } else {
        response = await gameApi.equipBackground({ background_id: confirmItem.id });
      }
      
      const profileData = response?.data?.profile || response?.profile;

      //서버가 준 최신 프로필 데이터로 스토어를 즉시 동기화합니다.
      // 이 안에 새로 장착한 캐릭터의 레벨과 경험치가 들어있습니다.
      if (profileData) {
        // 1. 프로필 데이터가 있으면 즉시 동기화
        syncGameProfile(profileData); 
      } else {
        // 2. 데이터가 없으면 전체 상태 새로고침 (로그 상 이 부분이 실행 중)
        // refreshGameState가 끝날 때까지 기다린 후 다음 줄로 넘어갑니다.
        await refreshGameState();
      }
      
      // ✅ 성공 시 팝업 닫기와 토스트를 비동기 작업 완료 후로 배치
      toast.success(`"${confirmItem.name}"을(를) 적용했습니다.`);
      setConfirmItem(null); 

    } catch (error: any) {
      console.error('장착 실패:', error);
      // 에러 메시지가 객체인 경우를 대비해 처리
      const errorMsg = error?.response?.data?.detail || error?.message || '장착에 실패했습니다.';
      toast.error(errorMsg);
      // 에러 발생 시에도 사용자가 다시 시도할 수 있도록 팝업 유지 또는 닫기 선택
      // 여기서는 안전을 위해 confirmItem을 null로 만들지 않고 버튼 활성화만 복구합니다.
    } finally {
      // ✅ finally에서 확실하게 상태 해제
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return createPortal(
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[200] flex items-center justify-center p-4"
      >
        <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />

        <motion.div
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.9, opacity: 0 }}
          className="relative w-full max-w-[380px] max-h-[70vh] overflow-y-auto bg-slate-900 rounded-2xl border border-violet-500/30 shadow-[0_0_40px_rgba(139,92,246,0.3)]"
        >
          {/* 헤더 */}
          <div className="sticky top-0 bg-slate-900/95 backdrop-blur-sm p-4 border-b border-white/10 flex items-center justify-between z-10">
            <h2 className="text-lg font-bold text-white">📦 보관함</h2>
            <button onClick={onClose} className="p-1 rounded-lg hover:bg-white/10">
              <X className="w-5 h-5 text-white/60" />
            </button>
          </div>

          {/* 탭 */}
          <div className="p-4 pb-2 flex gap-2">
            <button
              onClick={() => setActiveTab('character')}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl text-sm font-semibold border transition-all ${
                activeTab === 'character'
                  ? 'bg-violet-500/20 border-violet-400/30 text-violet-300'
                  : 'bg-white/5 border-white/10 text-white/50'
              }`}
            >
              <UserRound className="w-4 h-4" />
              캐릭터
            </button>
            <button
              onClick={() => setActiveTab('background')}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl text-sm font-semibold border transition-all ${
                activeTab === 'background'
                  ? 'bg-violet-500/20 border-violet-400/30 text-violet-300'
                  : 'bg-white/5 border-white/10 text-white/50'
              }`}
            >
              <Palette className="w-4 h-4" />
              배경
            </button>
          </div>

          <div className="p-4 pt-2 space-y-2">
            {activeTab === 'character'
              ? displayCharacters.map((char) => {
                  const isSelected = selectedCharacter === char.id;
                  const individualData = ownedCharacters.find(oc => oc.id === char.id);
                  const charLevel = individualData ? individualData.level : 1;

                  return (
                    <motion.button
                      key={char.id}
                      whileTap={{ scale: 0.98 }}
                      onClick={() => handleSelect(char.id, 'character', char.name)}
                      className={`w-full flex items-center gap-3 p-3 rounded-xl border transition-all ${
                        isSelected
                          ? 'bg-violet-500/15 border-violet-400/30'
                          : 'bg-white/5 border-white/10 hover:bg-white/10'
                      }`}
                    >
                      <span className="text-3xl">
                        <div className="w-12 h-12 flex items-center justify-center shrink-0">
                          <img 
                            src={char.iconSrc} 
                            alt={char.name}
                            className="w-full h-full object-contain"
                            style={{ transform: `scale(${(char.scale || 1) * 0.8})` }} 
                          />
                        </div>
                      </span>
                      
                      <div className="flex-1 text-left">
                        <p className="text-sm font-semibold text-white">{char.name}</p>
                        <p className="text-[10px] text-violet-300">Lv.{charLevel}</p>
                      </div>
                      {isSelected && (
                        <div className="w-6 h-6 rounded-full bg-violet-500/30 border border-violet-400/50 flex items-center justify-center">
                          <Check className="w-3.5 h-3.5 text-violet-300" />
                        </div>
                      )}
                    </motion.button>
                  );
                })
              : ownedBackgrounds.map((bg) => {
                  const isSelected = selectedBackground === bg.id;
                  return (
                    <motion.button
                      key={bg.id}
                      whileTap={{ scale: 0.98 }}
                      onClick={() => handleSelect(bg.id, 'background', bg.name)}
                      className={`w-full flex items-center gap-3 p-3 rounded-xl border transition-all ${
                        isSelected
                          ? 'bg-violet-500/15 border-violet-400/30'
                          : 'bg-white/5 border-white/10 hover:bg-white/10'
                      }`}
                    >
                      <div className="w-12 h-8 rounded-lg border border-white/10 shrink-0 overflow-hidden relative">
                        {bg.imageSrc ? (
                          <img 
                            src={bg.imageSrc} 
                            alt={bg.name}
                            className="w-full h-full object-cover" 
                          />
                        ) : (
                          <div 
                            className="w-full h-full" 
                            style={{ background: bg.gradient }} 
                          />
                        )}
                      </div>

                      <div className="flex-1 text-left">
                        <p className="text-sm font-semibold text-white">{bg.name}</p>
                      </div>
                      {isSelected && (
                        <div className="w-6 h-6 rounded-full bg-violet-500/30 border border-violet-400/50 flex items-center justify-center">
                          <Check className="w-3.5 h-3.5 text-violet-300" />
                        </div>
                      )}
                    </motion.button>
                  );
                })}
          </div>
        </motion.div>

        {/* 확인 팝업 */}
        <AnimatePresence>
          {confirmItem && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-[210] flex items-center justify-center p-6"
            >
              <div className="absolute inset-0 bg-black/50" onClick={() => !submitting && setConfirmItem(null)} />
              <motion.div
                initial={{ scale: 0.9 }}
                animate={{ scale: 1 }}
                exit={{ scale: 0.9 }}
                className="relative bg-slate-900 rounded-2xl border border-violet-500/30 p-5 w-full max-w-[300px]"
              >
                <p className="text-sm text-white/70 text-center mb-4">
                  이 <span className="text-white font-bold">{confirmItem.name}</span>
                  ({confirmItem.type === 'character' ? '캐릭터' : '배경화면'})을
                  <br />
                  선택하시겠습니까?
                </p>

                <div className="flex gap-2">
                  <button
                    onClick={() => setConfirmItem(null)}
                    disabled={submitting}
                    className="flex-1 py-2.5 rounded-xl bg-white/10 border border-white/10 text-white/70 text-sm font-medium disabled:opacity-50"
                  >
                    아니요
                  </button>
                  <button
                    onClick={handleConfirm}
                    disabled={submitting}
                    className="flex-1 py-2.5 rounded-xl bg-gradient-to-r from-violet-600 to-purple-600 text-white text-sm font-semibold border border-white/20 disabled:opacity-60"
                  >
                    {submitting ? '처리 중...' : '예'}
                  </button>
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </AnimatePresence>,
    document.body
  );
};

export default StorageDialog;
