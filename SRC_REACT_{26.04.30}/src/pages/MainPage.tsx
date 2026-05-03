/**
 * 🏠 메인 대시보드 페이지 컴포넌트
 * 
 * 로그인 후 표시되는 메인 화면입니다.
 * 건강 상태 요약과 챌린지 게임 진입 버튼을 제공합니다.
 * 
 * 📝 수정 가이드:
 * - 건강 상태 카드: hasInBodyData 조건부 렌더링 부분 수정
 * - 게임 진입 버튼: handleGameStart 함수 및 버튼 UI 수정
 * - 인사말 변경: user?.nickname 표시 부분 수정
 * - 트랜지션: GameTransition, GameExitTransition 컴포넌트 수정
 * 
 * 🔄 트랜지션 흐름:
 * - 게임 진입: GameTransition (1.5초 표시 후 /game 이동)
 * - 게임 퇴장: GameExitTransition (게임에서 돌아올 때 2초 표시)
 * 
 * ⚠️ 게임 진입 조건:
 * - Samsung Health 연동 완료
 * - 목표 체중 설정 완료
 */

import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate, useLocation } from 'react-router-dom';
import { Lock, Sparkles, Gamepad2, ChevronRight, Zap } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import AppLayout from '@/components/AppLayout';
import { toast } from 'sonner';
import GameTransition from '@/components/GameTransition';

// 게임 나가기 트랜지션 컴포넌트
const GameExitTransition = ({ isActive, onComplete }: { isActive: boolean; onComplete: () => void }) => {
  useEffect(() => {
    if (isActive) {
      // 아이콘 1.5초 표시 + 배경 슬라이드 0.5초 = 총 2초
      const timer = setTimeout(onComplete, 2000);
      return () => clearTimeout(timer);
    }
  }, [isActive, onComplete]);

  return (
    <AnimatePresence>
      {isActive && (
        <motion.div
          className="fixed inset-0 z-[100] flex items-center justify-center overflow-hidden max-w-[430px] mx-auto left-0 right-0"
          initial={{ opacity: 1 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          {/* 게임 창 오버레이 - 1.5초 후 닫히는 효과 */}
          <motion.div
            className="absolute inset-0 bg-gradient-to-br from-slate-900 via-violet-900 to-purple-900"
            initial={{ scale: 1, borderRadius: "0%" }}
            animate={{ scale: 0, borderRadius: "100%" }}
            transition={{ duration: 0.5, ease: "easeOut", delay: 1.5 }}
          />
          
          {/* 배경 오버레이 - 1.5초 후 서서히 사라짐 */}
          <motion.div
            className="absolute inset-0 bg-black/40"
            initial={{ opacity: 1 }}
            animate={{ opacity: 0 }}
            transition={{ duration: 0.3, delay: 1.4 }}
          />


          {/* 메인 콘텐츠 */}
          <div className="relative z-10 flex flex-col items-center gap-6">
            {/* 메인 아이콘 영역 - 1.5바퀴 회전 후 사라짐 */}
            <motion.div
              className="relative"
              initial={{ scale: 1, rotate: 0, opacity: 1 }}
              animate={{ 
                scale: [1, 1, 1.15, 0],
                rotate: [0, 0, 270, 540],
                opacity: [1, 1, 1, 0]
              }}
              transition={{ 
                duration: 2,
                times: [0, 0.75, 0.9, 1],
                ease: "easeInOut"
              }}
            >
              {/* 글로우 효과 */}
              <motion.div
                className="absolute inset-0 bg-yellow-400/30 rounded-full blur-2xl"
                initial={{ scale: 1.3, opacity: 0.8 }}
                animate={{ scale: 0, opacity: 0 }}
                transition={{ duration: 0.5, delay: 1.4 }}
              />
              
              {/* 메인 아이콘 */}
              <div className="relative w-28 h-28 bg-gradient-to-br from-violet-600 to-purple-700 rounded-2xl flex items-center justify-center border-4 border-white/30 shadow-2xl">
                <Gamepad2 className="w-14 h-14 text-white drop-shadow-[0_2px_4px_rgba(0,0,0,0.5)]" />
                
                {/* 코너 장식 */}
                <div className="absolute -top-1 -left-1 w-3 h-3 bg-white rounded-sm" />
                <div className="absolute -top-1 -right-1 w-3 h-3 bg-white rounded-sm" />
                <div className="absolute -bottom-1 -left-1 w-3 h-3 bg-white rounded-sm" />
                <div className="absolute -bottom-1 -right-1 w-3 h-3 bg-white rounded-sm" />
              </div>

              {/* 주변 아이콘들 */}
              <motion.div
                className="absolute -top-2 -right-2"
                initial={{ rotate: 0, opacity: 1 }}
                animate={{ rotate: -540, scale: 0, opacity: 0 }}
                transition={{ duration: 0.5, delay: 1.35 }}
              >
                <Sparkles className="w-6 h-6 text-yellow-400" />
              </motion.div>
              <motion.div
                className="absolute -bottom-2 -left-2"
                initial={{ scale: 1, opacity: 1 }}
                animate={{ scale: 0, opacity: 0 }}
                transition={{ duration: 0.4, delay: 1.4 }}
              >
                <Zap className="w-6 h-6 text-white" />
              </motion.div>
            </motion.div>

            {/* 텍스트 영역 */}
            <motion.div
              className="text-center"
              initial={{ opacity: 1, y: 0 }}
              animate={{ opacity: 0, y: -20 }}
              transition={{ delay: 1.4, duration: 0.4 }}
            >
              <motion.h2
                className="text-3xl font-black text-white mb-2 drop-shadow-[0_4px_8px_rgba(0,0,0,0.8)]"
                initial={{ scale: 1 }}
                animate={{ scale: [1, 1.05, 1] }}
                transition={{ duration: 0.35, repeat: 1 }}
                style={{ textShadow: '0 2px 10px rgba(0,0,0,0.9), 0 0 30px rgba(139,92,246,0.5)' }}
              >
                게임 나가는 중!
              </motion.h2>
              <p className="text-white text-sm font-medium drop-shadow-[0_2px_4px_rgba(0,0,0,0.8)]">다음에 또 만나요</p>
            </motion.div>

            {/* 로딩 도트 */}
            <motion.div 
              className="flex gap-2"
              initial={{ opacity: 1 }}
              animate={{ opacity: 0 }}
              transition={{ delay: 1.35, duration: 0.3 }}
            >
              {[0, 1, 2].map((i) => (
                <motion.div
                  key={i}
                  className="w-3 h-3 bg-white rounded-full"
                  animate={{ y: [-5, 5, -5] }}
                  transition={{
                    duration: 0.35,
                    repeat: 2,
                    delay: i * 0.06,
                  }}
                />
              ))}
            </motion.div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

const MainPage = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const { hasInBodyData, hasMissionsGenerated, user, targetWeight } = useAppStore();
  const [showGameTransition, setShowGameTransition] = useState(false);
  const [showExitTransition, setShowExitTransition] = useState(false);

  // 게임에서 돌아왔을 때 나가기 애니메이션 표시
  useEffect(() => {
    if (location.state?.fromGame) {
      setShowExitTransition(true);
      // state 초기화 (뒤로 가기 시 재트리거 방지)
      window.history.replaceState({}, document.title);
    }
  }, [location.state]);

  const handleExitTransitionComplete = () => {
    setShowExitTransition(false);
  };

  const handleGameStart = () => {
    // 목표 체중 미설정 시 안내
    if (!targetWeight) {
      toast.warning('먼저 목표 체중을 설정해주세요.', {
        description: '신체 분석 페이지에서 목표 체중을 설정할 수 있어요.',
        action: {
          label: '설정하기',
          onClick: () => navigate('/inbody'),
        },
      });
      return;
    }
    
    // 게임 진입 시 항상 트랜지션 표시
    setShowGameTransition(true);
  };

  const handleGameTransitionComplete = () => {
    setShowGameTransition(false);
    navigate('/game');
  };

  return (
    <AppLayout>
      {/* 🎮 게임 진입 트랜지션 */}
      <GameTransition 
        isActive={showGameTransition} 
        onComplete={handleGameTransitionComplete} 
      />

      {/* 🎮 게임 나가기 트랜지션 */}
      <GameExitTransition 
        isActive={showExitTransition} 
        onComplete={handleExitTransitionComplete} 
      />

      {/* Header */}
      <div className="gradient-primary px-6 pt-safe-top pb-12">
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-primary-foreground"
        >
          <p className="text-primary-foreground/80 text-sm">안녕하세요,</p>
          <h1 className="text-2xl font-bold mt-1">{user?.nickname || '사용자'}님</h1>
        </motion.div>
      </div>

      {/* Main Content */}
      <div className="-mt-6 px-6 pb-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="bg-card rounded-2xl p-6 card-shadow-lg"
        >
          <h2 className="text-lg font-semibold text-foreground mb-4">
            오늘의 건강 상태
          </h2>
          
          {hasInBodyData ? (
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-card rounded-xl p-4 border border-border shadow-sm">
                <p className="text-sm text-muted-foreground">BMI</p>
                <p className="text-2xl font-bold text-foreground">23.0</p>
                <p className="text-xs text-success mt-1 flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-success" />
                  정상 범위
                </p>
              </div>
              <div className="bg-card rounded-xl p-4 border border-border shadow-sm">
                <p className="text-sm text-muted-foreground">체지방률</p>
                <p className="text-2xl font-bold text-foreground">18.5%</p>
                <p className="text-xs text-success mt-1 flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-success" />
                  적정 수준
                </p>
              </div>
            </div>
          ) : (
            <div className="bg-secondary/50 rounded-xl p-6 text-center">
              <Lock className="w-12 h-12 text-muted-foreground mx-auto mb-3" />
              <p className="text-muted-foreground">
                신체 정보를 입력하면<br />건강 상태를 확인할 수 있어요
              </p>
              <button
                onClick={() => navigate('/onboarding')}
                className="mt-4 text-primary font-semibold hover:underline"
              >
                정보 입력하기 →
              </button>
            </div>
          )}
        </motion.div>

        {/* Quick Actions */}
        {hasInBodyData && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className={`mt-4 rounded-2xl p-5 border ${
              hasMissionsGenerated 
                ? 'bg-gradient-to-r from-active/15 to-level/15 border-active/30' 
                : 'bg-gradient-to-r from-primary/10 to-info/10 border-primary/20'
            }`}
          >
            <div className="flex items-center gap-3">
              <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
                hasMissionsGenerated 
                  ? 'bg-gradient-to-br from-active to-level' 
                  : 'gradient-primary'
              }`}>
                {hasMissionsGenerated ? (
                  <Gamepad2 className="w-5 h-5 text-primary-foreground" />
                ) : (
                  <Sparkles className="w-5 h-5 text-primary-foreground" />
                )}
              </div>
              <div className="flex-1">
                <h3 className="font-semibold text-foreground">
                  {hasMissionsGenerated ? '챌린지 준비 완료!' : 'AI 미션 생성하기'}
                </h3>
                <p className="text-sm text-muted-foreground">
                  {hasMissionsGenerated ? '게임을 시작하고 레벨업 해보세요' : '맞춤형 챌린지를 시작해보세요'}
                </p>
              </div>
              {hasMissionsGenerated && (
                <ChevronRight className="w-5 h-5 text-active" />
              )}
            </div>
            <button
              onClick={handleGameStart}
              className={`mt-4 w-full py-3 rounded-xl font-semibold transition-all ${
                hasMissionsGenerated 
                  ? 'bg-gradient-to-r from-active to-level text-white hover:opacity-90' 
                  : 'gradient-primary text-primary-foreground'
              }`}
            >
              {hasMissionsGenerated ? '🎮 챌린지 게임 시작하기' : '미션 생성하기'}
            </button>
          </motion.div>
        )}
      </div>
    </AppLayout>
  );
};

export default MainPage;
