/**
 * 🧭 하단 네비게이션 바 컴포넌트
 * 
 * 앱 하단에 고정되는 네비게이션 바입니다.
 * 신체 분석, 챌린지, 프로필 페이지로 이동할 수 있습니다.
 * 
 * 📝 수정 가이드:
 * - 네비 아이템 추가/수정: navItems 배열 수정
 * - 아이콘 변경: 각 아이템의 icon 속성 수정
 * - 잠금 조건 변경: locked, disabled 속성 로직 수정
 * - 게임 버튼 스타일: item.isGame 조건부 스타일 수정
 * - 게임 페이지 배경: GameNavBackground 컴포넌트 수정
 * 
 * 🔒 접근 제한:
 * - 신체 분석: 신체 데이터 입력 후 활성화
 * - 챌린지: Samsung Health 연동 + 목표 체중 설정 후 활성화
 * - 프로필: 항상 활성화
 */

import { useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate, useLocation } from 'react-router-dom';
import { Activity, Gamepad2, User as UserIcon, Lock, Sparkles, Zap, Star } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import GameTransition from './GameTransition';
import { toast } from 'sonner';

/**
 * 🎮 게임 페이지용 네비게이션 배경
 * 
 * 게임 페이지에서만 표시되는 특별한 배경 효과입니다.
 * 별 파티클, 글로우 라인, 떠다니는 오브 등을 포함합니다.
 */
const GameNavBackground = () => (
  <div className="absolute inset-0 overflow-hidden pointer-events-none">
    {/* 🎨 그라데이션 배경 */}
    <div className="absolute inset-0 bg-gradient-to-t from-slate-900 via-violet-950/95 to-purple-950/90" />
    
    {/* ⭐ 작은 별 파티클 */}
    {[...Array(12)].map((_, i) => (
      <motion.div
        key={`nav-star-${i}`}
        className="absolute w-0.5 h-0.5 bg-white rounded-full"
        style={{
          left: `${5 + Math.random() * 90}%`,
          top: `${10 + Math.random() * 80}%`,
        }}
        animate={{
          opacity: [0.3, 1, 0.3],
          scale: [0.8, 1.2, 0.8],
        }}
        transition={{
          duration: 2 + Math.random() * 2,
          repeat: Infinity,
          delay: Math.random() * 2,
        }}
      />
    ))}
    
    {/* 📏 상단 글로우 라인 */}
    <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-violet-400/50 to-transparent" />
    
    {/* 🔮 떠다니는 오브 */}
    {[...Array(3)].map((_, i) => (
      <motion.div
        key={`nav-orb-${i}`}
        className="absolute w-20 h-20 rounded-full blur-2xl"
        style={{
          background: 'radial-gradient(circle, rgba(139,92,246,0.15) 0%, transparent 70%)',
          left: `${20 + i * 30}%`,
          top: '20%',
        }}
        animate={{
          x: [0, 10, 0],
          opacity: [0.3, 0.5, 0.3],
        }}
        transition={{
          duration: 4 + i,
          repeat: Infinity,
          delay: i * 0.5,
        }}
      />
    ))}
  </div>
);

const BottomNav = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { hasInBodyData, hasInBodySynced, hasMissionsGenerated, targetWeight } = useAppStore();
  const [showGameTransition, setShowGameTransition] = useState(false);

  // 🎮 게임 페이지 여부 확인
  const isGamePage = location.pathname === '/game';

  // 🔓 챌린지 버튼은 Samsung Health 연동된 경우에만 활성화
  const canAccessChallenge = hasInBodySynced;

  /**
   * 📱 네비게이션 아이템 설정
   * 
   * 새 네비 아이템 추가 시 이 배열에 객체 추가:
   * - id: 고유 식별자
   * - icon: lucide-react 아이콘
   * - label: 표시될 텍스트
   * - path: 이동할 경로
   * - locked: 잠금 상태 (잠금 아이콘 표시)
   * - disabled: 비활성화 상태 (클릭 불가)
   * - showSparkle: 스파클 아이콘 표시 여부
   * - isGame: 게임 버튼 특별 스타일 적용 여부
   */
  const navItems = [
    {
      id: 'inbody',
      icon: Activity,
      label: '신체 분석',
      path: '/inbody',
      locked: !hasInBodyData,
      disabled: false,
      isGame: false,
    },
    {
      id: 'game',
      icon: Gamepad2,
      label: '챌린지',
      path: '/game',
      locked: !canAccessChallenge,
      disabled: !canAccessChallenge,
      showSparkle: canAccessChallenge && !hasMissionsGenerated,
      isGame: true,
    },
    {
      id: 'profile',
      icon: UserIcon,
      label: '프로필',
      path: '/profile',
      locked: false,
      disabled: false,
      isGame: false,
    },
  ];

  /**
   * 🖱️ 네비게이션 아이템 클릭 핸들러
   * 
   * 잠금 상태, 비활성화 상태, 목표 체중 미설정 등을 체크합니다.
   */
  const handleNavClick = (item: typeof navItems[0]) => {
    // 이미 해당 페이지에 있으면 클릭 무시
    if (location.pathname === item.path) {
      return;
    }
    
    // 🔒 잠금 상태 처리
    if (item.locked) {
      if (item.id === 'inbody') {
        navigate('/onboarding');
      }
      return;
    }
    
    // ⛔ 비활성화 상태 처리
    if (item.disabled) {
      return;
    }
    
    // ⚖️ 챌린지 버튼 클릭 시 목표 체중 미설정 체크
    if (item.isGame && !targetWeight) {
      toast.warning('먼저 목표 체중을 설정해주세요.', {
        description: '신체 분석 페이지에서 목표 체중을 설정할 수 있어요.',
        action: {
          label: '설정하기',
          onClick: () => navigate('/inbody'),
        },
      });
      return;
    }
    
    // 🎮 게임 페이지로 이동 시 트랜지션 표시
    if (item.isGame) {
      setShowGameTransition(true);
    } else {
      navigate(item.path);
    }
  };

  /**
   * 🎬 게임 트랜지션 완료 핸들러
   */
  const handleGameTransitionComplete = () => {
    setShowGameTransition(false);
    navigate('/game');
  };

  /**
   * ✅ 현재 활성화된 탭 확인
   */
  const isActive = (path: string) => location.pathname === path;

  /**
   * 🎨 아이템 색상 결정
   * 
   * 게임 페이지와 일반 페이지에서 다른 색상 스킴을 사용합니다.
   */
  const getItemColor = (item: typeof navItems[0]) => {
    if (item.isGame) return '';
    
    if (isGamePage) {
      // 🌙 게임 페이지에서는 밝은 색상 사용
      if (isActive(item.path)) {
        return 'text-violet-300';
      }
      if (item.locked || item.disabled) {
        return 'text-white/30';
      }
      return 'text-white/70 hover:text-white';
    } else {
      // ☀️ 일반 페이지
      if (isActive(item.path)) {
        return 'text-primary';
      }
      if (item.locked || item.disabled) {
        return 'text-locked';
      }
      return 'text-muted-foreground hover:text-foreground';
    }
  };

  return (
    <>
      {/* 🎮 게임 진입 트랜지션 */}
      <GameTransition 
        isActive={showGameTransition} 
        onComplete={handleGameTransitionComplete} 
      />

      {/* 📱 네비게이션 바 */}
      <nav className={`relative px-4 py-3 safe-area-bottom ${
        isGamePage 
          ? 'border-t border-violet-500/20' 
          : 'bg-card border-t border-border'
      }`}>
        {/* 🎮 게임 페이지일 때만 특별 배경 표시 */}
        {isGamePage && <GameNavBackground />}
        
        <div className="relative z-10 flex justify-around items-center">
          {navItems.map((item) => (
            <motion.button
              key={item.id}
              onClick={() => handleNavClick(item)}
              disabled={item.disabled}
              whileTap={{ scale: 0.95 }}
              className={`flex flex-col items-center gap-1 p-2 relative transition-colors ${getItemColor(item)}`}
            >
              {/* 🔒 잠금 아이콘 (게임 버튼 제외) */}
              {item.locked && !item.isGame && (
                <div className="absolute -top-0.5 right-1">
                  <Lock className={`w-3 h-3 ${isGamePage ? 'text-white/40' : ''}`} />
                </div>
              )}
              
              {/* ✨ 스파클 아이콘 (미션 미생성 시) */}
              {item.showSparkle && (
                <motion.div 
                  className="absolute -top-0.5 right-1"
                  animate={{ scale: [1, 1.2, 1], rotate: [0, 10, -10, 0] }}
                  transition={{ duration: 1.5, repeat: Infinity }}
                >
                  <Sparkles className="w-3.5 h-3.5 text-yellow-400" />
                </motion.div>
              )}

              {/* 🎮 게임 버튼 (특별 스타일) */}
              {item.isGame ? (
                <div className="relative">
                  {/* 💫 글로우 효과 */}
                  {!item.locked && (
                    <motion.div
                      className="absolute inset-0 rounded-2xl bg-gradient-to-r from-violet-500 via-purple-600 to-indigo-600 opacity-60 blur-md"
                      animate={{
                        scale: [1, 1.15, 1],
                        opacity: [0.4, 0.7, 0.4],
                      }}
                      transition={{ duration: 2, repeat: Infinity }}
                    />
                  )}
                  
                  {/* 🕹️ 메인 게임 버튼 */}
                  <motion.div
                    className={`relative w-14 h-14 rounded-2xl flex items-center justify-center border-2 ${
                      item.locked
                        ? 'bg-locked/20 border-locked/30'
                        : isActive(item.path)
                          ? 'bg-gradient-to-br from-violet-600 via-purple-700 to-indigo-800 border-violet-400/50 shadow-[0_0_25px_rgba(139,92,246,0.7)]'
                          : 'bg-gradient-to-br from-violet-700 via-purple-800 to-indigo-900 border-violet-500/30 shadow-[0_0_20px_rgba(139,92,246,0.5)]'
                    }`}
                    whileHover={!item.locked ? { scale: 1.1 } : undefined}
                    transition={{ type: 'spring', stiffness: 400, damping: 17 }}
                  >
                    {item.locked ? (
                      <Lock className="w-6 h-6 text-locked" />
                    ) : (
                      <>
                        <item.icon className="w-7 h-7 text-white drop-shadow-[0_2px_4px_rgba(0,0,0,0.5)]" />
                        
                        {/* ⚡ 우측 상단 번개 아이콘 */}
                        <motion.div
                          className="absolute top-1 right-1"
                          animate={{ opacity: [0.5, 1, 0.5], scale: [0.8, 1, 0.8] }}
                          transition={{ duration: 1, repeat: Infinity }}
                        >
                          <Zap className="w-3 h-3 text-yellow-400" />
                        </motion.div>
                      </>
                    )}
                    
                    {/* 📐 코너 장식 (잠금 해제 시) */}
                    {!item.locked && (
                      <>
                        <div className="absolute -top-0.5 -left-0.5 w-2 h-2 bg-white/40 rounded-sm" />
                        <div className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-white/40 rounded-sm" />
                        <div className="absolute -bottom-0.5 -left-0.5 w-2 h-2 bg-white/40 rounded-sm" />
                        <div className="absolute -bottom-0.5 -right-0.5 w-2 h-2 bg-white/40 rounded-sm" />
                      </>
                    )}
                  </motion.div>
                </div>
              ) : (
                /* 📱 일반 버튼 (신체 분석, 프로필) */
                <motion.div 
                  className={`w-11 h-11 rounded-xl flex items-center justify-center ${
                    isGamePage
                      ? isActive(item.path)
                        ? 'bg-violet-500/30 border border-violet-400/30'
                        : item.locked || item.disabled
                          ? 'bg-white/5 border border-white/10'
                          : 'bg-white/10 border border-white/20 hover:bg-white/20'
                      : isActive(item.path)
                        ? 'bg-primary/10'
                        : item.locked || item.disabled
                          ? 'bg-locked/10'
                          : 'bg-secondary'
                  }`}
                  whileHover={!item.locked && !item.disabled ? { scale: 1.1 } : undefined}
                  transition={{ type: 'spring', stiffness: 400, damping: 17 }}
                >
                  <item.icon className="w-5 h-5" />
                </motion.div>
              )}
              
              {/* 🏷️ 라벨 */}
              <span className={`text-[11px] font-medium ${
                item.isGame && !item.locked
                  ? isGamePage ? 'text-violet-300 font-bold' : 'text-primary font-bold'
                  : ''
              }`}>
                {item.label}
              </span>
            </motion.button>
          ))}
        </div>
      </nav>
    </>
  );
};

export default BottomNav;
