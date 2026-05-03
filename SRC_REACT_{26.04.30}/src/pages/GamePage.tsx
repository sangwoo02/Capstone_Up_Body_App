/**
 * 🎮 챌린지 게임 페이지 - 서버 연동 버전
 *
 * 목표:
 * - 게임 진입 시 서버에서 health / game profile / missions 조회
 * - 결과에 따라 잠금 / AI 미션 생성하기 / 게임 메인 화면 분기
 * - generate-initial 호출 후 다시 서버 데이터 재조회
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import {
  Gamepad2,
  Lock,
  Sparkles,
  Target,
  Trophy,
  Zap,
  LogOut,
  Coins,
  Swords,
  Ticket,
  Plus,
  AlertTriangle,
  Shield,
  Crown,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAppStore } from '@/stores/appStore';
import { toast } from 'sonner';
import GameBottomNav, { type GameTab } from '@/components/game/GameBottomNav';
import PhotoCard from '@/components/game/PhotoCard';
import MissionsView from '@/components/game/MissionsView';
import ShopView from '@/components/game/ShopView';
import AchievementCelebration from '@/components/game/AchievementCelebration';
import { missionsApi } from '@/services/api';

// 게임 배경 컴포넌트
const GameBackground = ({ isAnimated = false }: { isAnimated?: boolean }) => {
  const stars = useMemo(
    () =>
      Array.from({ length: 10 }, (_, i) => ({
        id: i,
        left: `${Math.random() * 100}%`,
        top: `${Math.random() * 100}%`,
        duration: 3 + Math.random() * 2,
        delay: Math.random() * 1.5,
        size: Math.random() > 0.75 ? 'w-1.5 h-1.5' : 'w-1 h-1',
        opacity: 0.22 + Math.random() * 0.28,
      })),
    []
  );

  const orbs = useMemo(
    () =>
      Array.from({ length: 2 }, (_, i) => ({
        id: i,
        left: `${10 + Math.random() * 65}%`,
        top: `${10 + Math.random() * 65}%`,
        background:
          i % 2 === 0
            ? 'radial-gradient(circle, rgba(168,85,247,0.10) 0%, transparent 72%)'
            : 'radial-gradient(circle, rgba(236,72,153,0.08) 0%, transparent 72%)',
      })),
    []
  );

  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(255,116,38,0.08),_transparent_18%),radial-gradient(circle_at_80%_20%,_rgba(168,85,247,0.10),_transparent_22%),linear-gradient(to_bottom,_#120b22,_#18122a_38%,_#09111f)]" />

      {stars.map((star) =>
        isAnimated ? (
          <motion.div
            key={`star-${star.id}`}
            className={`absolute rounded-full bg-white ${star.size}`}
            style={{ left: star.left, top: star.top, opacity: star.opacity }}
            animate={{ opacity: [star.opacity * 0.65, star.opacity, star.opacity * 0.65] }}
            transition={{
              duration: star.duration,
              repeat: Infinity,
              delay: star.delay,
              ease: 'easeInOut',
            }}
          />
        ) : (
          <div
            key={`star-${star.id}`}
            className={`absolute rounded-full bg-white ${star.size}`}
            style={{ left: star.left, top: star.top, opacity: star.opacity }}
          />
        )
      )}

      {orbs.map((orb) => (
        <div
          key={`orb-${orb.id}`}
          className="absolute w-28 h-28 rounded-full blur-2xl"
          style={{
            background: orb.background,
            left: orb.left,
            top: orb.top,
          }}
        />
      ))}

      <div className="absolute -top-12 left-1/2 -translate-x-1/2 w-[115%] h-28 bg-orange-500/6 blur-2xl" />
      <div className="absolute bottom-0 left-0 right-0 h-32 bg-gradient-to-t from-violet-600/10 to-transparent" />
    </div>
  );
};

// 공통 로딩 화면
const GameLoadingScreen = ({
  title = '게임 시작',
  loadingText = '게임 데이터 로딩 중...',
}: {
  title?: string;
  loadingText?: string;
}) => {
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => {
      setProgress((prev) => Math.min(prev + 4, 96));
    }, 80);

    return () => clearInterval(interval);
  }, []);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center"
    >
      <div className="absolute inset-0 max-w-[430px] mx-auto left-0 right-0 overflow-hidden">
        <GameBackground />
      </div>

      <div className="relative z-10 text-center px-8 max-w-[430px] mx-auto">
        <motion.div
          animate={{ scale: [1, 1.08, 1], rotate: [0, 4, -4, 0] }}
          transition={{ duration: 2.2, repeat: Infinity }}
          className="relative w-24 h-24 mx-auto rounded-[28px] bg-gradient-to-b from-violet-500 to-purple-700 flex items-center justify-center mb-8 border border-white/20 shadow-[0_8px_0_rgba(91,33,182,0.9),0_0_40px_rgba(139,92,246,0.35)]"
        >
          <div className="absolute inset-x-3 top-2 h-1/3 rounded-full bg-white/15 blur-md" />
          <Gamepad2 className="relative w-12 h-12 text-white" />
        </motion.div>

        <p className="text-[11px] uppercase tracking-[0.24em] text-violet-200/70 font-bold mb-2">
          
        </p>
        <h2 className="text-2xl font-black text-white mb-2 [text-shadow:_0_2px_0_rgba(0,0,0,0.35)]">
          {title}
        </h2>
        <p className="text-white/70 mb-8">{loadingText}</p>

        <div className="w-64 mx-auto">
          <div className="h-3 rounded-full overflow-hidden border border-white/10 bg-black/30">
            <motion.div
              className="h-full rounded-full bg-gradient-to-r from-violet-500 via-fuchsia-500 to-orange-400"
              initial={{ width: 0 }}
              animate={{ width: `${progress}%` }}
            />
          </div>
          <p className="text-white/50 text-sm mt-2 font-mono">{progress}%</p>
        </div>
      </div>
    </motion.div>
  );
};

const GamePage = () => {
  const navigate = useNavigate();

  const {
    coins,
    missionCoins,
    hasCreatedCharacter,
    gameProfile,
    missions,
    isHealthLinked,
    isGameLoading,
    nickname,
    loadGameBootstrap,
    refreshGameState,
  } = useAppStore();

  const [activeTab, setActiveTab] = useState<GameTab>('home');
  const [isGenerating, setIsGenerating] = useState(false);
  const [generateError, setGenerateError] = useState(false);

  const fetchGameState = useCallback(async () => {
    try {
      await loadGameBootstrap();
    } catch (error) {
      console.error('게임 상태 조회 실패:', error);
      toast.error('게임 데이터를 불러오지 못했습니다.');
    }
  }, [loadGameBootstrap]);

  useEffect(() => {
    fetchGameState();
  }, [fetchGameState]);

  const handleGenerateMissions = async () => {
    try {
      setIsGenerating(true);
      setGenerateError(false);

      await missionsApi.generateInitial({
        force_regenerate: false,
      });

      toast.success('AI 미션이 생성되었습니다!');
      await refreshGameState();
    } catch (error: any) {
      console.error('AI 미션 생성 실패:', error);
      setGenerateError(true);
      toast.error(error?.message || 'AI 미션 생성에 실패했습니다.');
    } finally {
      setIsGenerating(false);
    }
  };

  const handleExit = () => {
    navigate('/inbody', {
      state: {
        fromGameExit: true,
      },
    });
  };

  const hasActiveMissions = missions.length > 0;
  const shouldShowGenerateButton = isHealthLinked && !hasActiveMissions;

  // 1) 최초 페이지 로딩
  if (isGameLoading) {
    return <GameLoadingScreen title="게임 데이터 확인" loadingText="게임 상태를 불러오는 중..." />;
  }

  // 2) 잠금 상태: Samsung Health 미연동
  if (!isHealthLinked) {
    return (
      <div className="h-full flex flex-col bg-background relative">
        <GameBackground isAnimated={false} />

        <div className="relative z-10 px-5 pt-safe-top pb-3">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-2xl bg-gradient-to-b from-violet-500 to-purple-700 flex items-center justify-center shadow-[0_5px_0_rgba(91,33,182,0.9)]">
              <Gamepad2 className="w-5 h-5 text-white" />
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-[0.22em] text-violet-200/70 font-bold">
                
              </p>
              <h1 className="text-xl font-black text-white">챌린지 게임</h1>
            </div>
          </div>
        </div>

        <div className="flex-1 flex items-center justify-center p-6 relative z-10">
          <motion.div
            initial={{ opacity: 0, scale: 0.94 }}
            animate={{ opacity: 1, scale: 1 }}
            className="w-full"
          >
            <div className="relative overflow-hidden rounded-[32px] p-[1px] bg-gradient-to-b from-violet-300/25 via-white/10 to-white/5">
              <div className="relative rounded-[31px] border border-white/5 bg-[linear-gradient(to_bottom,_rgba(255,255,255,0.06),_rgba(255,255,255,0.03))] backdrop-blur-md p-6 text-center">
                <div className="absolute inset-x-6 top-3 h-12 rounded-full bg-white/10 blur-xl" />

                <div className="w-24 h-24 mx-auto rounded-[28px] bg-gradient-to-b from-violet-500 to-fuchsia-700 border border-violet-200/15 flex items-center justify-center mb-6 shadow-[0_8px_0_rgba(126,34,206,0.92)]">
                  <Lock className="w-12 h-12 text-white" />
                </div>

                <p className="text-[11px] uppercase tracking-[0.22em] text-violet-200/60 font-bold">
                  Access Locked
                </p>
                <h2 className="text-2xl font-black text-white mt-2 [text-shadow:_0_2px_0_rgba(0,0,0,0.35)]">
                  게임 잠금
                </h2>

                <p className="text-white/70 mt-3 max-w-xs mx-auto leading-relaxed">
                  게임을 시작하려면 먼저
                  <br />
                  Samsung Health 연동이 필요합니다
                </p>

                <Button
                  onClick={() => navigate('/onboarding')}
                  className="mt-8 w-full h-[58px] rounded-[22px] bg-gradient-to-b from-violet-500 to-purple-700 text-white font-black border border-white/20 shadow-[0_6px_0_rgba(91,33,182,0.92),0_12px_20px_rgba(0,0,0,0.25)] active:translate-y-[3px] active:shadow-[0_2px_0_rgba(91,33,182,0.92),0_6px_12px_rgba(0,0,0,0.2)]"
                >
                  정보 입력하기
                </Button>
              </div>
            </div>
          </motion.div>
        </div>
      </div>
    );
  }

  // 3) AI 미션 미생성 상태
  if (shouldShowGenerateButton) {
    return (
      <div className="h-full flex flex-col bg-background relative">
        <GameBackground isAnimated={false} />

        <div className="relative z-10 px-5 pt-safe-top pb-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-2xl bg-gradient-to-b from-violet-500 to-purple-700 flex items-center justify-center shadow-[0_5px_0_rgba(91,33,182,0.9)]">
              <Gamepad2 className="w-5 h-5 text-white" />
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-[0.22em] text-violet-200/70 font-bold">
                
              </p>
              <h1 className="text-xl font-black text-white">챌린지 게임</h1>
            </div>
          </div>

          <motion.button
            onClick={handleExit}
            whileTap={{ scale: 0.95 }}
            className="h-11 px-4 rounded-2xl bg-gradient-to-b from-violet-500/90 to-purple-700/90 backdrop-blur-sm border border-white/20 text-white font-black shadow-[0_4px_0_rgba(91,33,182,0.9)]"
          >
            <div className="flex items-center gap-2">
              <LogOut className="w-4 h-4" />
              <span className="text-sm">나가기</span>
            </div>
          </motion.button>
        </div>

        <div className="flex-1 flex flex-col items-center justify-center p-5 relative z-10">
          <motion.div
            initial={{ opacity: 0, y: 18 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-center w-full"
          >
            {generateError ? (
              <div className="relative overflow-hidden rounded-[32px] p-[1px] bg-gradient-to-b from-red-300/30 via-orange-300/10 to-white/5">
                <div className="relative rounded-[31px] border border-red-300/10 bg-[linear-gradient(to_bottom,_rgba(239,68,68,0.12),_rgba(255,255,255,0.03))] backdrop-blur-md p-6">
                  <div className="absolute inset-x-6 top-3 h-12 rounded-full bg-white/10 blur-xl" />

                  <div className="w-20 h-20 mx-auto rounded-[24px] bg-gradient-to-b from-red-500 to-orange-600 border border-red-200/15 flex items-center justify-center mb-5 shadow-[0_7px_0_rgba(153,27,27,0.92)]">
                    <AlertTriangle className="w-10 h-10 text-white" />
                  </div>

                  <p className="text-[11px] uppercase tracking-[0.2em] text-red-200/60 font-bold">
                    Generation Error
                  </p>
                  <h2 className="text-xl font-black text-white mt-2">오류 발생</h2>
                  <p className="text-white/70 text-sm mt-2 max-w-xs mx-auto">
                    오류로 인해 AI 미션 생성에 실패했습니다.
                  </p>

                  <Button
                    onClick={handleGenerateMissions}
                    disabled={isGenerating}
                    className="mt-6 w-full h-[58px] rounded-[22px] bg-gradient-to-b from-red-500 to-orange-600 text-white font-black border border-white/20 shadow-[0_6px_0_rgba(153,27,27,0.92),0_12px_20px_rgba(0,0,0,0.25)] active:translate-y-[3px] active:shadow-[0_2px_0_rgba(153,27,27,0.92),0_6px_12px_rgba(0,0,0,0.2)]"
                  >
                    {isGenerating ? (
                      <div className="flex items-center gap-3">
                        <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        <span>재생성 중...</span>
                      </div>
                    ) : (
                      <>
                        <Sparkles className="w-5 h-5 mr-2" />
                        다시 생성하기
                      </>
                    )}
                  </Button>
                </div>
              </div>
            ) : (
              <div className="relative overflow-hidden rounded-[32px] p-[1px] bg-gradient-to-b from-violet-300/25 via-pink-300/10 to-white/5">
                <div className="relative rounded-[31px] border border-white/5 bg-[linear-gradient(to_bottom,_rgba(255,255,255,0.06),_rgba(255,255,255,0.03))] backdrop-blur-md p-6">
                  <div className="absolute inset-x-6 top-3 h-12 rounded-full bg-white/10 blur-xl" />

                  <motion.div
                    animate={{ scale: [1, 1.05, 1], rotate: [0, 4, -4, 0] }}
                    transition={{ duration: 2, repeat: Infinity, repeatType: 'reverse' }}
                    className="relative w-20 h-20 mx-auto rounded-[24px] bg-gradient-to-b from-violet-500 to-fuchsia-700 flex items-center justify-center mb-5 border border-white/20 shadow-[0_7px_0_rgba(91,33,182,0.92),0_0_30px_rgba(168,85,247,0.22)]"
                  >
                    <Sparkles className="w-10 h-10 text-white" />
                    <motion.div
                      className="absolute inset-0 rounded-[24px] bg-violet-400/20"
                      animate={{ scale: [1, 1.45], opacity: [0.45, 0] }}
                      transition={{ duration: 1.6, repeat: Infinity }}
                    />
                  </motion.div>

                  <p className="text-[11px] uppercase tracking-[0.22em] text-violet-200/65 font-bold">
                    AI Mission Forge
                  </p>
                  <h2 className="text-xl font-black text-white mt-2">AI 미션 생성</h2>

                  <p className="text-white/70 text-sm mt-2 max-w-xs mx-auto leading-relaxed">
                    AI가 신체 데이터를 분석해서
                    <br />
                    맞춤형 건강 미션을 생성해드려요
                  </p>

                  <div className="mt-6 space-y-2.5">
                    {[
                      { icon: Target, label: '개인 맞춤 AI 미션', delay: 0.1, colors: 'from-orange-400 to-red-500' },
                      { icon: Trophy, label: '경험치 · 레벨업 · 경쟁전', delay: 0.2, colors: 'from-yellow-400 to-orange-500' },
                      { icon: Zap, label: '업적 · 메달 시스템', delay: 0.3, colors: 'from-cyan-400 to-blue-500' },
                    ].map((item) => (
                      <motion.div
                        key={item.label}
                        initial={{ opacity: 0, x: -18 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: item.delay }}
                        className="flex items-center gap-3 rounded-2xl p-3 border border-white/8 bg-white/[0.04] backdrop-blur-sm"
                      >
                        <div className={`w-10 h-10 rounded-xl bg-gradient-to-b ${item.colors} flex items-center justify-center shadow-[0_4px_0_rgba(0,0,0,0.2)]`}>
                          <item.icon className="w-4 h-4 text-white" />
                        </div>
                        <span className="font-bold text-white text-sm">{item.label}</span>
                      </motion.div>
                    ))}
                  </div>

                  <Button
                    onClick={handleGenerateMissions}
                    disabled={isGenerating}
                    className="mt-6 w-full h-[58px] rounded-[22px] bg-gradient-to-b from-violet-500 to-purple-700 text-white font-black border border-white/20 shadow-[0_6px_0_rgba(91,33,182,0.92),0_12px_20px_rgba(0,0,0,0.25)] active:translate-y-[3px] active:shadow-[0_2px_0_rgba(91,33,182,0.92),0_6px_12px_rgba(0,0,0,0.2)]"
                  >
                    {isGenerating ? (
                      <div className="flex items-center gap-3">
                        <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                        <span>AI가 미션을 생성 중...</span>
                      </div>
                    ) : (
                      <>
                        <Sparkles className="w-5 h-5 mr-2" />
                        미션 생성하기
                      </>
                    )}
                  </Button>
                </div>
              </div>
            )}
          </motion.div>
        </div>
      </div>
    );
  }

  // 4) health는 연결됐지만 프로필/미션 조회가 비정상인 경우
  if (!gameProfile && !hasActiveMissions) {
    return (
      <div className="h-full flex flex-col bg-background relative">
        <GameBackground />

        <div className="relative z-10 px-5 pt-safe-top pb-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-2xl bg-gradient-to-b from-violet-500 to-purple-700 flex items-center justify-center shadow-[0_5px_0_rgba(91,33,182,0.9)]">
              <Gamepad2 className="w-5 h-5 text-white" />
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-[0.22em] text-violet-200/70 font-bold">
                
              </p>
              <h1 className="text-xl font-black text-white">챌린지 게임</h1>
            </div>
          </div>

          <motion.button
            onClick={handleExit}
            whileTap={{ scale: 0.95 }}
            className="h-11 px-4 rounded-2xl bg-gradient-to-b from-violet-500/90 to-purple-700/90 backdrop-blur-sm border border-white/20 text-white font-black shadow-[0_4px_0_rgba(91,33,182,0.9)]"
          >
            <div className="flex items-center gap-2">
              <LogOut className="w-4 h-4" />
              <span className="text-sm">나가기</span>
            </div>
          </motion.button>
        </div>

        <div className="flex-1 flex items-center justify-center p-6 relative z-10">
          <div className="w-full text-center">
            <div className="relative overflow-hidden rounded-[32px] p-[1px] bg-gradient-to-b from-violet-300/25 via-white/10 to-white/5">
              <div className="rounded-[31px] border border-white/5 bg-[linear-gradient(to_bottom,_rgba(255,255,255,0.06),_rgba(255,255,255,0.03))] p-6 backdrop-blur-md">
                <div className="w-20 h-20 mx-auto rounded-[24px] bg-gradient-to-b from-violet-500 to-fuchsia-700 border border-white/20 flex items-center justify-center mb-5 shadow-[0_7px_0_rgba(91,33,182,0.92)]">
                  <Shield className="w-10 h-10 text-white" />
                </div>

                <h2 className="text-xl font-black text-white">게임 데이터를 아직 시작하지 않았습니다</h2>
                <p className="text-white/55 text-sm mt-2">AI 미션 생성 버튼으로 시작해보세요</p>

                <Button
                  onClick={handleGenerateMissions}
                  disabled={isGenerating}
                  className="mt-6 w-full h-[58px] rounded-[22px] bg-gradient-to-b from-violet-500 to-purple-700 text-white font-black border border-white/20 shadow-[0_6px_0_rgba(91,33,182,0.92),0_12px_20px_rgba(0,0,0,0.25)] active:translate-y-[3px] active:shadow-[0_2px_0_rgba(91,33,182,0.92),0_6px_12px_rgba(0,0,0,0.2)]"
                >
                  {isGenerating ? '생성 중...' : 'AI 미션 생성하기'}
                </Button>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // 5) 메인 게임 화면
  return (
    <div className="h-full flex flex-col bg-background relative">
      <GameBackground isAnimated={activeTab === 'home'} />

      <AchievementCelebration />

      <div className="relative z-10 px-5 pt-safe-top pb-3 flex items-center justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-11 h-11 rounded-2xl bg-gradient-to-b from-violet-500 to-purple-700 flex items-center justify-center shadow-[0_5px_0_rgba(91,33,182,0.9)] shrink-0">
            <Crown className="w-5 h-5 text-white" />
          </div>

          <div className="min-w-0">
            <p className="text-[11px] uppercase tracking-[0.22em] text-violet-200/70 font-bold">
              
            </p>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-black text-white leading-none [text-shadow:_0_2px_0_rgba(0,0,0,0.35)]">
                챌린지
              </h1>

              {nickname ? (
                <span className="text-[10px] font-black text-violet-200 bg-violet-500/20 px-2.5 py-1 rounded-full border border-violet-300/20 truncate max-w-[120px]">
                  {nickname}
                </span>
              ) : hasCreatedCharacter ? (
                <span className="text-[10px] text-white/40 bg-white/10 px-2.5 py-1 rounded-full border border-white/10">
                  닉네임 설정 필요
                </span>
              ) : null}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <motion.button
            whileTap={{ scale: 0.95 }}
            onClick={() => navigate('/mission-coin-shop')}
            className="h-9 px-3 rounded-full border border-cyan-300/20 bg-cyan-500/15 backdrop-blur-sm shadow-[0_2px_0_rgba(8,145,178,0.65)]"
          >
            <div className="flex items-center gap-1">
              <Ticket className="w-3.5 h-3.5 text-cyan-300" />
              <span className="text-xs font-black text-cyan-200">{missionCoins}</span>
              <Plus className="w-3 h-3 text-cyan-300/60" />
            </div>
          </motion.button>

          <div className="h-9 px-3 rounded-full border border-yellow-300/20 bg-yellow-500/15 backdrop-blur-sm shadow-[0_2px_0_rgba(146,64,14,0.65)]">
            <div className="flex items-center gap-1 h-full">
              <Coins className="w-3.5 h-3.5 text-yellow-300" />
              <span className="text-xs font-black text-yellow-200">{coins}</span>
            </div>
          </div>

          <motion.button
            onClick={handleExit}
            whileTap={{ scale: 0.95 }}
            className="w-9 h-9 rounded-xl bg-white/10 border border-white/10 text-white/70 hover:bg-white/15 transition-all"
          >
            <LogOut className="w-4 h-4 mx-auto" />
          </motion.button>
        </div>
      </div>

      <AnimatePresence initial={false} mode="wait">
        {activeTab === 'home' ? (
          <motion.div
            key="home"
            initial={false}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            className="flex-1 overflow-y-auto relative z-10 px-5 pb-4"
          >
            <div className="mb-4">
              <div className="relative rounded-[34px] p-[1.5px] bg-[linear-gradient(180deg,rgba(196,181,253,0.28)_0%,rgba(255,255,255,0.08)_22%,rgba(139,92,246,0.10)_58%,rgba(255,255,255,0.03)_100%)]">
                <div className="relative rounded-[32px] p-[1px] bg-[linear-gradient(180deg,rgba(255,255,255,0.07)_0%,rgba(255,255,255,0.02)_100%)]">
                  <div className="relative rounded-[31px] border border-white/[0.06] bg-[linear-gradient(to_bottom,_rgba(255,255,255,0.045),_rgba(255,255,255,0.02))] backdrop-blur-md p-2 overflow-visible">

                    {/* 🔹 상단 광택 (더 자연스럽게 축소) */}
                    <div className="pointer-events-none absolute inset-x-8 top-2 h-7 rounded-full bg-white/7 blur-lg" />

                    {/* 🔹 내부 경계 부드럽게 */}
                    <div className="pointer-events-none absolute inset-0 rounded-[31px] shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]" />

                    {/* 🔹 컬러 오라 (강도 줄임) */}
                    <div className="pointer-events-none absolute -right-10 top-8 w-24 h-24 rounded-full bg-violet-400/6 blur-2xl" />
                    <div className="pointer-events-none absolute -left-8 bottom-6 w-20 h-20 rounded-full bg-fuchsia-400/5 blur-2xl" />

                    <PhotoCard />
                  </div>
                </div>
              </div>
            </div>
            {/* Week Walk 버튼은 그대로 유지 */}
            <div className="w-full">
              <motion.button
                whileTap={{ scale: 0.95 }}
                onClick={() => {
                  if (!hasCreatedCharacter) {
                    toast('닉네임을 먼저 설정해주세요!', { icon: '🔒' });
                    return;
                  }
                  navigate('/week-walk');
                }}
                className={`w-full relative rounded-[22px] p-4 overflow-hidden transition-all duration-150 ${
                  hasCreatedCharacter
                    ? 'border border-orange-200/20 bg-gradient-to-b from-orange-400/90 via-orange-500/85 to-red-600/90 shadow-[0_6px_0_rgba(124,45,18,0.95),0_12px_24px_rgba(0,0,0,0.35)] active:translate-y-[3px] active:shadow-[0_2px_0_rgba(124,45,18,0.95),0_6px_12px_rgba(0,0,0,0.28)]'
                    : 'border border-white/10 bg-gradient-to-b from-zinc-700/40 to-zinc-900/40 opacity-60 shadow-[0_6px_0_rgba(20,20,20,0.8)]'
                }`}
              >
                {hasCreatedCharacter && (
                  <>
                    <div className="absolute inset-x-3 top-2 h-1/3 rounded-full bg-white/20 blur-md pointer-events-none" />
                    <div className="absolute left-0 top-0 h-full w-20 -skew-x-12 bg-white/10 pointer-events-none" />
                    <div className="absolute right-6 top-0 h-full w-10 -skew-x-12 bg-yellow-200/10 pointer-events-none" />
                  </>
                )}

                {!hasCreatedCharacter && (
                  <div className="absolute top-2 right-2">
                    <Lock className="w-3 h-3 text-white/25" />
                  </div>
                )}

                <div className="flex items-center gap-4">
                  <div
                    className={`w-14 h-14 rounded-[16px] flex items-center justify-center transition-all ${
                      hasCreatedCharacter
                        ? 'bg-gradient-to-b from-red-700 via-red-800 to-red-950 border border-white/15 shadow-[inset_0_2px_0_rgba(255,255,255,0.12),0_4px_10px_rgba(0,0,0,0.28)]'
                        : 'bg-white/5 border border-white/10'
                    }`}
                  >
                    <Swords
                      className={`w-7 h-7 ${
                        hasCreatedCharacter
                          ? 'text-white drop-shadow-[0_2px_2px_rgba(0,0,0,0.35)]'
                          : 'text-white/50'
                      }`}
                    />
                  </div>

                  <div className="text-left">
                    <p
                      className={`text-[20px] leading-none font-black tracking-[-0.02em] ${
                        hasCreatedCharacter
                          ? 'text-white [text-shadow:_0_2px_0_rgba(120,53,15,0.9),_0_4px_10px_rgba(0,0,0,0.28)]'
                          : 'text-white/70'
                      }`}
                    >
                      Week Walk
                    </p>
                    <p
                      className={`text-[11px] mt-1 font-bold tracking-[0.18em] uppercase ${
                        hasCreatedCharacter ? 'text-yellow-100/90' : 'text-white/35'
                      }`}
                    >
                      경쟁전 - 주간 누적 걸음수를 통한 경쟁 시스템
                    </p>
                  </div>
                </div>
              </motion.button>
            </div>
          </motion.div>
        ) : activeTab === 'missions' ? (
          <motion.div
            key="missions"
            initial={false}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.12 }}
            className="flex-1 overflow-hidden flex flex-col relative z-10"
          >
            <MissionsView />
          </motion.div>
        ) : (
        <motion.div
          key="shop"
          initial={false}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.12 }}
          className="flex-1 overflow-hidden flex flex-col relative z-10"
        >
            <ShopView />
          </motion.div>
        )}
      </AnimatePresence>

      <GameBottomNav
        activeTab={activeTab}
        onTabChange={setActiveTab}
        isLocked={!hasCreatedCharacter}
      />
    </div>
  );
};

export default GamePage;