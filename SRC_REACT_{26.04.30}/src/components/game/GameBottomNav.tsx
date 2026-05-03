/**
 * 🎮 게임 내 하단 네비게이션 - 게임화 디자인
 * 라인 없이 배경과 자연스럽게 융합되는 게임 스타일 UI
 * 캐릭터 미생성 시 AI미션/상점 잠금
 */

import { motion } from 'framer-motion';
import { ScrollText, Gamepad2, ShoppingBag, Sparkles, Lock } from 'lucide-react';
import { toast } from 'sonner';

export type GameTab = 'missions' | 'home' | 'shop';

interface GameBottomNavProps {
  activeTab: GameTab;
  onTabChange: (tab: GameTab) => void;
  isLocked?: boolean; // 캐릭터 미생성 시 미션/상점 잠금
}

const GameBottomNav = ({ activeTab, onTabChange, isLocked = false }: GameBottomNavProps) => {
  const sideItems: { id: GameTab; icon: typeof ScrollText; label: string; accentFrom: string; accentTo: string; glowColor: string }[] = [
    { id: 'missions', icon: ScrollText, label: 'AI 미션', accentFrom: 'from-cyan-500', accentTo: 'to-blue-600', glowColor: 'rgba(6,182,212,0.5)' },
    { id: 'shop', icon: ShoppingBag, label: '상점', accentFrom: 'from-amber-500', accentTo: 'to-orange-600', glowColor: 'rgba(245,158,11,0.5)' },
  ];

  return (
    <div className="relative z-10 px-4 pb-5 pt-8 safe-area-bottom bg-transparent">

      <div className="flex items-end justify-around -translate-y-3">
        {/* 왼쪽: AI 미션 */}
        {(() => {
          const item = sideItems[0];
          const isActive = activeTab === item.id;
          return (
            <motion.button
              key={item.id}
              onClick={() => {
                if (isLocked) { toast('캐릭터를 먼저 생성해주세요!', { icon: '🔒' }); return; }
                onTabChange(item.id);
              }}
              whileTap={{ scale: isLocked ? 1 : 0.88 }}
              className={`flex flex-col items-center gap-1 relative ${isLocked ? 'opacity-40' : ''}`}
            >
              <motion.div
                className={`relative w-14 h-14 rounded-2xl flex items-center justify-center overflow-hidden transition-all duration-200 ${
                  isActive
                    ? `bg-gradient-to-br ${item.accentFrom} ${item.accentTo} border-2 border-cyan-300/50`
                    : 'bg-white/[0.06] border border-white/[0.12]'
                }`}
                animate={isActive ? { y: -4 } : { y: 0 }}
                style={isActive ? { boxShadow: `0 8px 24px -4px ${item.glowColor}` } : {}}
              >
                {isActive && (
                  <div className="absolute inset-0 bg-gradient-to-t from-white/15 to-transparent" />
                )}
                {isLocked ? <Lock className="w-5 h-5 relative z-10 text-white/30" /> : <item.icon className={`w-6 h-6 relative z-10 ${isActive ? 'text-white drop-shadow-lg' : 'text-white/40'}`} />}
              </motion.div>
              <span className={`text-[10px] font-bold tracking-wide ${isActive ? 'text-cyan-300' : 'text-white/30'}`}>
                {item.label}
              </span>
            </motion.button>
          );
        })()}

        {/* 중앙: 홈 (대형 버튼) */}
        {(() => {
          const isActive = activeTab === 'home';
          return (
            <motion.button
              onClick={() => onTabChange('home')}
              whileTap={{ scale: 0.9 }}
              className="flex flex-col items-center relative -mt-3"
            >
              <motion.div
                className={`relative w-[72px] h-[72px] rounded-[22px] flex items-center justify-center overflow-hidden transition-all duration-200 ${
                  isActive
                    ? 'bg-gradient-to-br from-violet-500 via-purple-600 to-indigo-700 border-[2.5px] border-violet-300/50'
                    : 'bg-white/[0.08] border-2 border-white/[0.15]'
                }`}
                animate={isActive ? { y: -6 } : { y: 0 }}
                style={isActive ? { boxShadow: '0 10px 30px -6px rgba(139,92,246,0.7), 0 0 0 3px rgba(139,92,246,0.15)' } : {}}
              >
                {/* 내부 광택 효과 */}
                {isActive && (
                  <>
                    <div className="absolute inset-0 bg-gradient-to-t from-transparent via-white/8 to-white/20" />
                    <motion.div
                      className="absolute -top-1 -right-1 w-4 h-4"
                      animate={{ rotate: [0, 180, 360], scale: [0.8, 1.2, 0.8] }}
                      transition={{ duration: 3, repeat: Infinity }}
                    >
                      <Sparkles className="w-4 h-4 text-yellow-300/80" />
                    </motion.div>
                  </>
                )}
                <Gamepad2 className={`w-8 h-8 relative z-10 ${isActive ? 'text-white drop-shadow-lg' : 'text-white/40'}`} />
              </motion.div>
              <span className={`text-[10px] font-bold tracking-wide mt-1 ${isActive ? 'text-violet-300' : 'text-white/30'}`}>
                홈
              </span>
            </motion.button>
          );
        })()}

        {/* 오른쪽: 상점 */}
        {(() => {
          const item = sideItems[1];
          const isActive = activeTab === item.id;
          return (
            <motion.button
              key={item.id}
              onClick={() => {
                if (isLocked) { toast('캐릭터를 먼저 생성해주세요!', { icon: '🔒' }); return; }
                onTabChange(item.id);
              }}
              whileTap={{ scale: isLocked ? 1 : 0.88 }}
              className={`flex flex-col items-center gap-1 relative ${isLocked ? 'opacity-40' : ''}`}
            >
              <motion.div
                className={`relative w-14 h-14 rounded-2xl flex items-center justify-center overflow-hidden transition-all duration-200 ${
                  isActive
                    ? `bg-gradient-to-br ${item.accentFrom} ${item.accentTo} border-2 border-amber-300/50`
                    : 'bg-white/[0.06] border border-white/[0.12]'
                }`}
                animate={isActive ? { y: -4 } : { y: 0 }}
                style={isActive ? { boxShadow: `0 8px 24px -4px ${item.glowColor}` } : {}}
              >
                {isActive && (
                  <div className="absolute inset-0 bg-gradient-to-t from-white/15 to-transparent" />
                )}
                {isLocked ? <Lock className="w-5 h-5 relative z-10 text-white/30" /> : <item.icon className={`w-6 h-6 relative z-10 ${isActive ? 'text-white drop-shadow-lg' : 'text-white/40'}`} />}
              </motion.div>
              <span className={`text-[10px] font-bold tracking-wide ${isActive ? 'text-amber-300' : 'text-white/30'}`}>
                {item.label}
              </span>
            </motion.button>
          );
        })()}
      </div>
    </div>
  );
};

export default GameBottomNav;
