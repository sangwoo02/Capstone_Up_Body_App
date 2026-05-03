/**
 * 🏆 업적 다이얼로그
 *
 * - 달성 업적은 활성화 표시
 * - 달성 업적 중 최대 3개를 선택하여 포토카드 뱃지로 장착
 * - 미달성 업적은 반투명 잠금 표시
 */

import { motion, AnimatePresence } from 'framer-motion';
import { X, Trophy, Check } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import { ACHIEVEMENTS } from './gameData';
import { gameApi } from '@/services/api';
import { toast } from 'sonner';
import { createPortal } from 'react-dom';


interface AchievementsDialogProps {
  open: boolean;
  onClose: () => void;
}

const AchievementsDialog = ({ open, onClose }: AchievementsDialogProps) => {
  const { equippedBadges, completedAchievements, refreshGameState } = useAppStore();

  const isCompleted = (achId: string) => completedAchievements.includes(achId);
  const isEquipped = (achId: string) => equippedBadges.includes(achId);

  const handleToggleBadge = async (achId: string) => {
    if (!isCompleted(achId)) return;

    try {
      let nextCodes: string[];

      if (isEquipped(achId)) {
        nextCodes = equippedBadges.filter((id) => id !== achId);
      } else {
        if (equippedBadges.length >= 3) {
          nextCodes = [...equippedBadges.slice(1), achId];
        } else {
          nextCodes = [...equippedBadges, achId];
        }
      }

      await gameApi.equipAchievements({
        achievement_codes: nextCodes,
      });

      await refreshGameState();
    } catch (error: any) {
      console.error('업적 장착 실패:', error);
      toast.error(error?.message || '업적 장착에 실패했습니다.');
    }
  };

  if (!open) return null;

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
            <div className="flex items-center gap-2">
              <Trophy className="w-5 h-5 text-yellow-400" />
              <h2 className="text-lg font-bold text-white">업적</h2>
              <span className="text-[10px] text-white/40 bg-white/10 px-2 py-0.5 rounded-full">
                뱃지 {equippedBadges.length}/3
              </span>
            </div>
            <button onClick={onClose} className="p-1 rounded-lg hover:bg-white/10">
              <X className="w-5 h-5 text-white/60" />
            </button>
          </div>

          <div className="p-4 space-y-2">
            {ACHIEVEMENTS.map((ach) => {
              const completed = isCompleted(ach.id);
              const equipped = isEquipped(ach.id);

              return (
                <motion.div
                  key={ach.id}
                  whileTap={completed ? { scale: 0.98 } : undefined}
                  onClick={() => handleToggleBadge(ach.id)}
                  className={`flex items-center gap-3 p-3 rounded-xl border cursor-pointer transition-all ${
                    completed
                      ? equipped
                        ? 'bg-yellow-500/15 border-yellow-400/30'
                        : 'bg-white/5 border-white/15 hover:bg-white/10'
                      : 'bg-white/3 border-white/5 opacity-40 cursor-not-allowed'
                  }`}
                >
                  <div
                    className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                      completed ? 'bg-yellow-500/20' : 'bg-white/5'
                    }`}
                  >
                    <span className="text-xl">{ach.badge}</span>
                  </div>

                  <div className="flex-1 min-w-0">
                    <h4 className="text-sm font-semibold text-white truncate">{ach.title}</h4>
                    <p className="text-[10px] text-white/40">{ach.description}</p>
                  </div>

                  {completed && equipped && (
                    <div className="shrink-0 w-6 h-6 rounded-full bg-yellow-500/30 border border-yellow-400/50 flex items-center justify-center">
                      <Check className="w-3.5 h-3.5 text-yellow-300" />
                    </div>
                  )}

                  {completed && !equipped && (
                    <div className="shrink-0 w-6 h-6 rounded-full bg-white/10 border border-white/20 flex items-center justify-center">
                      <span className="text-[8px] text-white/40">+</span>
                    </div>
                  )}
                </motion.div>
              );
            })}

            <p className="text-center text-white/30 text-xs pt-2">
              달성한 업적을 탭하여 포토카드에 뱃지를 장착하세요 (최대 3개)
            </p>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body
  );
};

export default AchievementsDialog;
