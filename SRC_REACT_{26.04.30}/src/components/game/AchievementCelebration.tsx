/**
 * 🎉 업적 달성 축하 팝업
 *
 * - 챌린지 페이지 내에서 어디서든 표시됨
 * - 달성 알림 + 적절한 빵빠레 이펙트
 * - "확인했어요!" 버튼으로 닫기
 */

import { motion, AnimatePresence } from 'framer-motion';
import { useAppStore } from '@/stores/appStore';
import { ACHIEVEMENTS } from './gameData';

const AchievementCelebration = () => {
  const { pendingAchievements, dismissPendingAchievements } = useAppStore();

  if (pendingAchievements.length === 0) return null;

  const currentAchId = pendingAchievements[0];
  const achievement = ACHIEVEMENTS.find((a) => a.id === currentAchId);

  if (!achievement) {
    dismissPendingAchievements();
    return null;
  }

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[100] flex items-center justify-center p-4"
      >
        <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

        {/* 빵빠레 파티클 */}
        <div className="absolute inset-0 pointer-events-none overflow-hidden">
          {[...Array(24)].map((_, i) => {
            const angle = (i / 24) * Math.PI * 2 + (Math.random() - 0.5) * 0.4;
            const distance = 180 + Math.random() * 200;
            const dx = Math.cos(angle) * distance;
            const dy = Math.sin(angle) * distance;
            return (
              <motion.div
                key={i}
                initial={{
                  opacity: 0,
                  x: 0,
                  y: 0,
                  scale: 0,
                }}
                animate={{
                  opacity: [0, 1, 1, 0],
                  x: dx,
                  y: dy,
                  scale: [0, 1.2, 1, 0.6],
                  rotate: Math.random() * 540 - 270,
                }}
                transition={{
                  duration: 1.8 + Math.random() * 0.8,
                  delay: Math.random() * 0.2,
                  ease: 'easeOut',
                }}
                className="absolute left-1/2 top-1/2 text-lg"
              >
                {['🎊', '🎉', '✨', '⭐', '🌟', '💫', '🎀', '🎈'][i % 8]}
              </motion.div>
            );
          })}
        </div>

        <motion.div
          initial={{ scale: 0, rotate: -10 }}
          animate={{ scale: 1, rotate: 0 }}
          exit={{ scale: 0 }}
          transition={{ type: 'spring', damping: 15 }}
          className="relative bg-slate-900 rounded-2xl border border-yellow-500/40 p-6 w-full max-w-[320px] text-center shadow-[0_0_60px_rgba(234,179,8,0.3)]"
        >
          {/* 
            🏅 업적 아이콘 위치
            나중에 커스텀 훈장 이미지로 교체 시:
            <img src={`/assets/badges/${achievement.id}.png`} className="w-16 h-16 mx-auto" />
          */}
        
          <motion.div
            animate={{ scale: [1, 1.15, 1], rotate: [0, 5, -5, 0] }}
            transition={{ duration: 1.5, repeat: Infinity }}
            className="w-20 h-20 mx-auto rounded-2xl bg-yellow-500/20 border border-yellow-400/30 flex items-center justify-center mb-4"
          >
            <span className="text-4xl">{achievement.badge}</span>
          </motion.div>

          <h3 className="text-lg font-bold text-yellow-300 mb-1">🎉 업적 달성!</h3>
          <p className="text-xl font-black text-white mb-1">{achievement.title}</p>
          <p className="text-sm text-white/50">{achievement.description}</p>

          <motion.button
            whileTap={{ scale: 0.95 }}
            onClick={dismissPendingAchievements}
            className="mt-5 w-full py-3 rounded-xl bg-gradient-to-r from-yellow-500 to-orange-500 text-white font-semibold text-sm border border-white/20 shadow-[0_0_20px_rgba(234,179,8,0.4)]"
          >
            확인했어요! 🥳
          </motion.button>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};

export default AchievementCelebration;
/*개발자 : 박상우, 장서빈, 오유나, 조병진*/