import { motion, AnimatePresence } from 'framer-motion';
import { Gamepad2, Sparkles, Zap } from 'lucide-react';

interface GameTransitionProps {
  isActive: boolean;
  onComplete: () => void;
}

/**
 * 🎮 게임 진입 트랜지션 컴포넌트
 * 
 * 이 컴포넌트는 챌린지/게임 화면으로 진입할 때 표시되는 애니메이션입니다.
 * 
 * 📝 수정 가이드:
 * - 배경색 변경: 아래 "bg-gradient-to-br from-game-dark via-primary to-game-accent" 부분 수정
 * - 아이콘 변경: Gamepad2, Sparkles, Zap 아이콘을 원하는 것으로 교체
 * - 텍스트 변경: "게임 시작!" 텍스트 수정
 * - 애니메이션 속도: duration 값 조정 (현재 0.5~1초)
 * - 픽셀 아트 추가: PixelCharacter 컴포넌트 영역에 이미지 삽입
 */

const GameTransition = ({ isActive, onComplete }: GameTransitionProps) => {
  return (
    <AnimatePresence>
      {isActive && (
        <motion.div
          className="absolute inset-0 z-50 flex items-center justify-center overflow-hidden"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.3 }}
          onAnimationComplete={() => {
            // 애니메이션 완료 후 페이지 이동 (1.5초 표시)
            setTimeout(onComplete, 1500);
          }}
        >
          {/* 🎨 배경 그라데이션 - 여기서 색상 수정 가능 */}
          <motion.div
            className="absolute inset-0 bg-gradient-to-br from-slate-900 via-violet-900 to-purple-900"
            initial={{ scale: 0, borderRadius: "100%" }}
            animate={{ scale: 3, borderRadius: "0%" }}
            transition={{ duration: 0.5, ease: "easeOut" }}
          />
          
          {/* 배경 오버레이 - 가독성 향상 */}
          <motion.div
            className="absolute inset-0 bg-black/40"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.3, delay: 0.2 }}
          />

          {/* 반짝이는 파티클 효과 - 컨테이너 내부에서만 동작 */}
          <div className="absolute inset-0 overflow-hidden">
            {[...Array(15)].map((_, i) => (
              <motion.div
                key={i}
                className="absolute w-2 h-2 bg-game-xp rounded-full"
                initial={{
                  left: "50%",
                  top: "50%",
                  opacity: 0,
                  scale: 0,
                }}
                animate={{
                  left: `${10 + Math.random() * 80}%`,
                  top: `${10 + Math.random() * 80}%`,
                  opacity: [0, 1, 0],
                  scale: [0, 1.5, 0],
                }}
                transition={{
                  duration: 1,
                  delay: 0.2 + i * 0.05,
                  ease: "easeOut",
                }}
              />
            ))}
          </div>

          {/* 메인 콘텐츠 */}
          <div className="relative z-10 flex flex-col items-center gap-6">
            {/* 
              🎮 픽셀 캐릭터 영역
              여기에 실제 픽셀 아트 이미지를 넣으시면 됩니다.
              예: <img src="/your-pixel-character.png" alt="캐릭터" className="w-32 h-32" />
            */}
            <motion.div
              className="relative"
              initial={{ scale: 0, rotate: -180 }}
              animate={{ scale: 1, rotate: 0 }}
              transition={{ duration: 0.5, delay: 0.3, type: "spring" }}
            >
              {/* 글로우 효과 */}
              <motion.div
                className="absolute inset-0 bg-game-xp/30 rounded-full blur-2xl"
                animate={{
                  scale: [1, 1.3, 1],
                  opacity: [0.5, 0.8, 0.5],
                }}
                transition={{ duration: 1, repeat: Infinity }}
              />
              
              {/* 
                🎨 메인 아이콘/캐릭터 영역
                현재: Gamepad2 아이콘
                변경 방법: 이 div 안의 내용을 이미지로 교체
                예: <img src="/pixel-hero.gif" className="w-24 h-24 pixelated" />
              */}
              <div className="relative w-28 h-28 bg-gradient-to-br from-violet-600 to-purple-700 rounded-2xl flex items-center justify-center border-4 border-white/30 shadow-2xl">
                <Gamepad2 className="w-14 h-14 text-white drop-shadow-[0_2px_4px_rgba(0,0,0,0.5)]" />
                
                {/* 코너 장식 - 픽셀 스타일 */}
                <div className="absolute -top-1 -left-1 w-3 h-3 bg-white rounded-sm" />
                <div className="absolute -top-1 -right-1 w-3 h-3 bg-white rounded-sm" />
                <div className="absolute -bottom-1 -left-1 w-3 h-3 bg-white rounded-sm" />
                <div className="absolute -bottom-1 -right-1 w-3 h-3 bg-white rounded-sm" />
              </div>

              {/* 주변 아이콘들 */}
              <motion.div
                className="absolute -top-2 -right-2"
                animate={{ rotate: 360 }}
                transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
              >
                <Sparkles className="w-6 h-6 text-game-xp" />
              </motion.div>
              <motion.div
                className="absolute -bottom-2 -left-2"
                animate={{ scale: [1, 1.2, 1] }}
                transition={{ duration: 0.5, repeat: Infinity }}
              >
                <Zap className="w-6 h-6 text-white" />
              </motion.div>
            </motion.div>

            {/* 🎮 텍스트 영역 - 여기서 문구 수정 가능 */}
            <motion.div
              className="text-center"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.5 }}
            >
              <motion.h2
                className="text-3xl font-black text-white mb-2 drop-shadow-[0_4px_8px_rgba(0,0,0,0.8)]"
                animate={{ scale: [1, 1.05, 1] }}
                transition={{ duration: 0.5, repeat: Infinity }}
                style={{ textShadow: '0 2px 10px rgba(0,0,0,0.9), 0 0 30px rgba(139,92,246,0.5)' }}
              >
                게임 시작!
              </motion.h2>
              <p className="text-white text-sm font-medium drop-shadow-[0_2px_4px_rgba(0,0,0,0.8)]">레벨업 챌린지에 도전하세요</p>
            </motion.div>

            {/* 로딩 도트 */}
            <div className="flex gap-2">
              {[0, 1, 2].map((i) => (
                <motion.div
                  key={i}
                  className="w-3 h-3 bg-white rounded-full"
                  animate={{ y: [-5, 5, -5] }}
                  transition={{
                    duration: 0.6,
                    repeat: Infinity,
                    delay: i * 0.1,
                  }}
                />
              ))}
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

export default GameTransition;
