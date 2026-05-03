/**
 * ⚔️ Week Walk 경쟁전 페이지
 *
 * 주간 걸음수 랭킹 + 시즌 점수 랭킹 시스템
 * - 주간 걸음수: 월~일 누적 걸음수 경쟁 (매주 초기화)
 * - 시즌 점수: 2달 단위 시즌, 꾸준함 평가
 * - 티어 시스템: 경쟁전 점수 누적에 따라 티어 분류
 */

import { useState, useEffect, useMemo, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  Swords,
  Trophy,
  Medal,
  Crown,
  Footprints,
  Timer,
  Star,
  Flame,
  Shield,
  Zap,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useAppStore } from '@/stores/appStore';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { weekWalkApi } from '@/services/api';
import { toast } from 'sonner';
import type {
  WeeklyRankingItem,
  SeasonRankingItem,
} from '@/types';


// ── 티어 정의 ──
const TIERS = [
  { name: '브론즈', minScore: 0, color: 'from-amber-700 to-amber-900', icon: Shield, textColor: 'text-amber-400' },
  { name: '실버', minScore: 500, color: 'from-slate-300 to-slate-600', icon: Shield, textColor: 'text-slate-200' },
  { name: '골드', minScore: 1500, color: 'from-yellow-300 to-yellow-600', icon: Star, textColor: 'text-yellow-300' },
  { name: '플래티넘', minScore: 3500, color: 'from-cyan-300 to-cyan-600', icon: Zap, textColor: 'text-cyan-300' },
  { name: '다이아', minScore: 7000, color: 'from-blue-400 to-purple-500', icon: Crown, textColor: 'text-blue-300' },
  { name: '마스터', minScore: 15000, color: 'from-red-500 to-pink-600', icon: Flame, textColor: 'text-red-300' },
];

function getTier(score: number) {
  for (let i = TIERS.length - 1; i >= 0; i--) {
    if (score >= TIERS[i].minScore) return TIERS[i];
  }
  return TIERS[0];
}

// ── 주간 보상 테이블 ──
const WEEKLY_REWARDS: { label: string; exp: number; coins: number; coupons: number; score: number }[] = [
  { label: '1위', exp: 500, coins: 300, coupons: 5, score: 200 },
  { label: '2위', exp: 350, coins: 200, coupons: 3, score: 150 },
  { label: '3위', exp: 250, coins: 150, coupons: 2, score: 120 },
  { label: '4~50위', exp: 100, coins: 50, coupons: 0, score: 80 },
  { label: '51~100위', exp: 50, coins: 30, coupons: 0, score: 50 },
  { label: '101~500위', exp: 30, coins: 0, coupons: 0, score: 30 },
  { label: '501~1000위', exp: 15, coins: 0, coupons: 0, score: 15 },
  { label: '1000위~', exp: 5, coins: 0, coupons: 0, score: 5 },
];

// ── 시즌 보상 테이블 (2달) ──
const SEASON_REWARDS: { label: string; badge: string; coins: number; coupons: number }[] = [
  { label: '1위', badge: '🥇 1위 훈장', coins: 1000, coupons: 20 },
  { label: '2위', badge: '🥈 2위 훈장', coins: 700, coupons: 15 },
  { label: '3위', badge: '🥉 3위 훈장', coins: 500, coupons: 10 },
  { label: '4~50위', badge: '⭐ 상위권 훈장', coins: 200, coupons: 0 },
  { label: '51~100위', badge: '🏵️ 도전자 훈장', coins: 100, coupons: 0 },
];

function formatCountdown(ms: number): string {
  if (ms <= 0) return '00:00:00';
  const hours = Math.floor(ms / 3600000);
  const mins = Math.floor((ms % 3600000) / 60000);
  const secs = Math.floor((ms % 60000) / 1000);
  return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
}


const RANKING_SCROLL_CLASS = 'max-h-[420px] overflow-y-auto pr-1';

function getDisplayRankingTitle(tab: 'weekly' | 'season', count: number) {
  return tab === 'weekly'
    ? `주간 걸음수 TOP ${Math.min(50, Math.max(count, 0))}`
    : `시즌 점수 TOP ${Math.min(50, Math.max(count, 0))}`;
}

function getRankAccent(rank: number, tab: 'weekly' | 'season') {
  if (rank === 1) return 'from-yellow-400/24 to-amber-500/12 border-yellow-300/40';
  if (rank === 2) return 'from-slate-300/18 to-slate-500/10 border-yellow-300/30';
  if (rank === 3) return 'from-orange-400/18 to-amber-700/10 border-yellow-300/25';

  return tab === 'weekly'
    ? 'from-orange-400/10 to-red-500/[0.06] border-yellow-300/20'
    : 'from-violet-500/12 to-fuchsia-500/[0.07] border-yellow-300/20';
}


const WeekWalkPage = () => {
  const navigate = useNavigate();
  const { nickname, refreshGameState, enqueueAchievementCelebration } = useAppStore();

  const [hasJoined, setHasJoined] = useState(false);
  const [showWarning, setShowWarning] = useState(false);
  const [countdown, setCountdown] = useState('');
  const [scoreCountdown, setScoreCountdown] = useState('');
  const [activeRankTab, setActiveRankTab] = useState<'weekly' | 'season'>('weekly');

  const [loading, setLoading] = useState(true);
  const [weeklySeasonEnd, setWeeklySeasonEnd] = useState<string | null>(null);
  const [scoreSeasonEnd, setScoreSeasonEnd] = useState<string | null>(null);

  const [weeklyRanking, setWeeklyRanking] = useState<WeeklyRankingItem[]>([]);
  const [seasonRanking, setSeasonRanking] = useState<SeasonRankingItem[]>([]);
  const [mySteps, setMySteps] = useState(0);
  const [myWeeklyRank, setMyWeeklyRank] = useState<number | null>(null);
  const [mySeasonRank, setMySeasonRank] = useState<number | null>(null);
  const [myScore, setMyScore] = useState(0);
  const [myTierName, setMyTierName] = useState('브론즈');
  const [myGameNickname, setMyGameNickname] = useState<string | null>(null);

  const weekEnd = useMemo(
    () => (weeklySeasonEnd ? new Date(weeklySeasonEnd) : null),
    [weeklySeasonEnd]
  );

  const backgroundStars = useMemo(
    () =>
      Array.from({ length: 20 }, (_, i) => ({
        id: i,
        left: `${Math.random() * 100}%`,
        top: `${Math.random() * 75}%`,
        duration: 2 + Math.random() * 3,
        delay: Math.random() * 2,
        size: Math.random() > 0.7 ? 'w-1.5 h-1.5' : 'w-1 h-1',
        opacity: 0.2 + Math.random() * 0.45,
      })),
    []
  );

  const scoreEnd = useMemo(
    () => (scoreSeasonEnd ? new Date(scoreSeasonEnd) : null),
    [scoreSeasonEnd]
  );

  const daysRemaining = useMemo(() => {
    if (!weekEnd) return 0;
    const diff = weekEnd.getTime() - Date.now();
    return Math.max(0, Math.ceil(diff / 86400000));
  }, [weekEnd]);

  useEffect(() => {
    loadOverview();
  }, []);

  useEffect(() => {
    if (!hasJoined || !weekEnd) return;

    const timer = setInterval(() => {
      const weeklyRemaining = weekEnd.getTime() - Date.now();
      setCountdown(formatCountdown(weeklyRemaining));

      if (weeklyRemaining <= 0) {
        setCountdown('시즌 종료!');
      }

      if (scoreEnd) {
        const scoreRemaining = scoreEnd.getTime() - Date.now();
        setScoreCountdown(formatCountdown(scoreRemaining));

        if (scoreRemaining <= 0) {
          setScoreCountdown('시즌 종료!');
        }
      }
    }, 1000);

    return () => clearInterval(timer);
  }, [hasJoined, weekEnd, scoreEnd]);

  const syncGameStateAndShowOwnAchievements = useCallback(
    async (achievementCodes?: string[]) => {
      const refreshed = await refreshGameState();

      const myCompletedCodes = new Set(
        refreshed.profile?.completed_achievement_codes ?? []
      );

      const ownNewAchievementCodes = (achievementCodes ?? []).filter((code) =>
        myCompletedCodes.has(code)
      );

      if (ownNewAchievementCodes.length > 0) {
        enqueueAchievementCelebration(ownNewAchievementCodes);
      }
    },
    [refreshGameState, enqueueAchievementCelebration]
  );

  const loadOverview = async () => {
    try {
      setLoading(true);

      const result = await weekWalkApi.getOverview();

      setHasJoined(!!result.my_weekly.joined);
      setWeeklySeasonEnd(result.weekly_season.end_at);
      setScoreSeasonEnd(result.score_season.end_at);

      setWeeklyRanking(
        result.weekly_ranking.map((item) => ({
          rank: item.rank,
          nickname: item.nickname,
          steps: item.steps || 0,
        }))
      );

      setSeasonRanking(
        result.score_ranking.map((item) => ({
          rank: item.rank,
          nickname: item.nickname,
          score: item.score || 0,
          tier: item.tier || '브론즈',
        }))
      );

      setMySteps(result.my_weekly.steps || 0);
      setMyWeeklyRank(result.my_weekly.rank);
      setMySeasonRank(result.my_score.rank);
      setMyScore(result.my_score.score || 0);
      setMyTierName(result.my_score.tier || '브론즈');
      setMyGameNickname(result.my_game_nickname || null);

      await syncGameStateAndShowOwnAchievements(result.new_achievement_codes);
    } catch (error: any) {
      console.error('Week Walk overview 실패:', error);
      toast.error(error?.message || '경쟁전 정보를 불러오지 못했습니다.');
      navigate('/game');
    } finally {
      setLoading(false);
    }
  };

  const handleJoin = async () => {
    if (daysRemaining <= 3) {
      setShowWarning(true);
      return;
    }

    try {
      const result = await weekWalkApi.join();

      await syncGameStateAndShowOwnAchievements(result.new_achievement_codes);

      toast.success(result.message || 'Week Walk 경쟁전에 참여했습니다.');
      setShowWarning(false);
      await loadOverview();
    } catch (error: any) {
      console.error('Week Walk 참가 실패:', error);
      toast.error(error?.message || '경쟁전 참여에 실패했습니다.');
    }
  };

  const myTier =
    TIERS.find((tier) => tier.name === myTierName) || getTier(myScore);

  const TierIcon = myTier.icon;

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-[radial-gradient(circle_at_top,_rgba(255,90,31,0.18),_transparent_30%),linear-gradient(to_bottom,_#120b22,_#1b1030_35%,_#0a0f1f)]">
        <div className="text-center">
          <div className="mx-auto mb-4 w-16 h-16 rounded-2xl bg-gradient-to-b from-orange-400 to-red-600 flex items-center justify-center shadow-[0_8px_0_rgba(120,53,15,0.95),0_0_30px_rgba(255,98,0,0.25)]">
            <Swords className="w-7 h-7 text-white" />
          </div>
          <p className="text-white font-black tracking-wide text-lg [text-shadow:_0_2px_0_rgba(0,0,0,0.4)]">
            WEEK WALK
          </p>
          <p className="text-white/50 text-sm mt-1">전투 정보를 불러오는 중...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col relative overflow-hidden bg-[radial-gradient(circle_at_top,_rgba(255,102,0,0.14),_transparent_22%),radial-gradient(circle_at_80%_20%,_rgba(168,85,247,0.16),_transparent_26%),linear-gradient(to_bottom,_#120b22,_#18122a_35%,_#09111f)]">
      {/* 배경 파티클 */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        {backgroundStars.map((star) => (
          <motion.div
            key={star.id}
            className={`absolute rounded-full bg-white ${star.size}`}
            style={{
              left: star.left,
              top: star.top,
              opacity: star.opacity,
            }}
            animate={{ opacity: [star.opacity * 0.5, star.opacity, star.opacity * 0.5] }}
            transition={{
              duration: star.duration,
              repeat: Infinity,
              delay: star.delay,
              ease: 'easeInOut',
            }}
          />
        ))}

        <div className="absolute -top-20 left-1/2 -translate-x-1/2 w-[140%] h-56 bg-orange-500/10 blur-3xl" />
        <div className="absolute top-40 -left-16 w-44 h-44 bg-fuchsia-500/10 rounded-full blur-3xl" />
        <div className="absolute bottom-10 -right-12 w-56 h-56 bg-cyan-500/10 rounded-full blur-3xl" />
      </div>

      {/* 헤더 */}
      <div className="relative z-10 px-5 pt-safe-top pb-3">
        <div className="flex items-center gap-3">
          <motion.button
            whileTap={{ scale: 0.9 }}
            onClick={() => navigate('/game')}
            className="relative p-2.5 rounded-2xl border border-white/10 bg-white/5 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] backdrop-blur-sm"
          >
            <div className="absolute inset-x-1 top-1 h-1/3 rounded-full bg-white/10 blur-sm" />
            <ArrowLeft className="relative w-5 h-5 text-white" />
          </motion.button>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-b from-orange-400 to-red-600 flex items-center justify-center shadow-[0_4px_0_rgba(120,53,15,0.95),0_0_20px_rgba(255,98,0,0.15)]">
                <Swords className="w-4 h-4 text-white" />
              </div>
              <div>
                <p className="text-[11px] tracking-[0.22em] uppercase text-orange-200/70 font-bold">
                  경쟁전
                </p>
                <h1 className="text-lg font-black text-white leading-none [text-shadow:_0_2px_0_rgba(0,0,0,0.35)]">
                  Week Walk
                </h1>
              </div>
            </div>
          </div>

          <Button
            type="button"
            onClick={() => navigate('/week-walk/rewards')}
            className="shrink-0 rounded-2xl border border-white/10 bg-white/5 px-4 py-2 text-xs font-bold text-white backdrop-blur-sm hover:bg-white/10"
          >
            보상 및 티어
          </Button>
        </div>
      </div>

      {/* 메인 */}
      <div className="flex-1 overflow-y-auto relative z-10 px-5 pb-16">
        {/* 상단 내 정보 패널 */}
        <motion.div
          initial={false}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.12 }}
          className="relative rounded-[28px] p-[1px] bg-gradient-to-b from-orange-300/25 via-white/10 to-white/5 mb-4"
        >
          <div className="relative overflow-hidden rounded-[27px] bg-[linear-gradient(to_bottom,_rgba(255,255,255,0.07),_rgba(255,255,255,0.03))] backdrop-blur-md border border-white/5 p-4">
            <div className="absolute inset-x-4 top-2 h-12 rounded-full bg-white/10 blur-xl pointer-events-none" />
            <div className="absolute right-0 top-0 w-28 h-28 bg-orange-400/10 rounded-full blur-2xl pointer-events-none" />

            <div className="relative flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className={`w-11 h-11 rounded-2xl bg-gradient-to-b ${myTier.color} flex items-center justify-center shadow-[0_4px_0_rgba(0,0,0,0.24)]`}>
                  <TierIcon className="w-5 h-5 text-white" />
                </div>
                <div>
                  <p className="text-[10px] uppercase tracking-[0.18em] text-white/45 font-bold">Tier</p>
                  <p className={`text-sm font-black ${myTier.textColor}`}>{myTier.name}</p>
                </div>
              </div>

              <div className="text-right">
                <p className="text-[10px] uppercase tracking-[0.18em] text-white/45 font-bold">Player</p>
                <p className="text-sm font-bold text-white max-w-[140px] truncate">
                  {myGameNickname || nickname || '미설정'}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="relative rounded-2xl border border-green-300/10 bg-gradient-to-b from-green-400/10 to-emerald-500/5 p-3 text-center overflow-hidden">
                <div className="absolute inset-x-3 top-1 h-6 rounded-full bg-white/8 blur-md" />
                <Footprints className="w-4 h-4 text-green-300 mx-auto mb-1.5" />
                <p className="text-[10px] text-white/50 font-semibold tracking-wide">이번 주 걸음</p>
                <p className="text-base font-black text-white mt-1">
                  {mySteps === 0 ? '-' : mySteps.toLocaleString()}
                </p>
                <p className="text-[10px] text-white/35 mt-1">
                  {myWeeklyRank ? `${myWeeklyRank}위` : '순위 집계 중'}
                </p>
              </div>

              <div className="relative rounded-2xl border border-yellow-300/10 bg-gradient-to-b from-yellow-400/10 to-orange-500/5 p-3 text-center overflow-hidden">
                <div className="absolute inset-x-3 top-1 h-6 rounded-full bg-white/8 blur-md" />
                <Trophy className="w-4 h-4 text-yellow-300 mx-auto mb-1.5" />
                <p className="text-[10px] text-white/50 font-semibold tracking-wide">시즌 점수</p>
                <p className="text-base font-black text-white mt-1">
                  {myScore.toLocaleString()}
                </p>
                <p className="text-[10px] text-white/35 mt-1">
                  {myScore === 0
                    ? '집계 전'
                    : mySeasonRank
                      ? `${mySeasonRank}위`
                      : '집계 전'}
                </p>
              </div>
            </div>
          </div>
        </motion.div>

        <AnimatePresence initial={false} mode="wait">
          {!hasJoined ? (
            <motion.div
              key="join"
              initial={false}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.12 }}
              className="mb-4"
            >
              {/* 설명 패널 */}
              <div className="relative rounded-[28px] p-[1px] bg-gradient-to-b from-red-300/30 via-orange-200/10 to-white/5 mb-4">
                <div className="relative overflow-hidden rounded-[27px] border border-red-300/10 bg-[linear-gradient(to_bottom,_rgba(255,116,38,0.12),_rgba(255,255,255,0.03))] p-4 backdrop-blur-md">
                  <div className="absolute inset-x-4 top-2 h-10 rounded-full bg-white/10 blur-lg" />
                  <div className="absolute -right-6 -top-6 w-24 h-24 bg-orange-400/10 rounded-full blur-2xl" />

                  <div className="relative flex items-center gap-2 mb-4">
                    <div className="w-9 h-9 rounded-xl bg-gradient-to-b from-orange-400 to-red-600 flex items-center justify-center shadow-[0_4px_0_rgba(120,53,15,0.95)]">
                      <Swords className="w-4 h-4 text-white" />
                    </div>
                    <div>
                      <p className="text-[11px] uppercase tracking-[0.2em] text-orange-200/65 font-bold">
                        Entry Briefing
                      </p>
                      <h2 className="text-base font-black text-white">경쟁전 안내</h2>
                    </div>
                  </div>

                  <ul className="space-y-2.5 text-xs text-white/75">
                    <li className="flex items-start gap-2.5 rounded-xl bg-white/[0.03] border border-white/5 px-3 py-2">
                      <span className="text-orange-300 mt-0.5">⚔️</span>
                      <span>매주 월~일 누적 걸음수로 겨루는 <strong className="text-white">주간 경쟁전</strong>입니다</span>
                    </li>
                    <li className="flex items-start gap-2.5 rounded-xl bg-white/[0.03] border border-white/5 px-3 py-2">
                      <span className="text-yellow-300 mt-0.5">🏆</span>
                      <span>순위에 따라 <strong className="text-white">EXP, 코인, 미션 쿠폰</strong>을 획득합니다</span>
                    </li>
                    <li className="flex items-start gap-2.5 rounded-xl bg-white/[0.03] border border-white/5 px-3 py-2">
                      <span className="text-cyan-300 mt-0.5">🛡️</span>
                      <span>누적 점수에 따라 <strong className="text-white">티어</strong>가 상승합니다</span>
                    </li>
                    <li className="flex items-start gap-2.5 rounded-xl bg-white/[0.03] border border-white/5 px-3 py-2">
                      <span className="text-fuchsia-300 mt-0.5">👑</span>
                      <span>2달마다 <strong className="text-white">시즌 랭킹 보상</strong>이 지급됩니다</span>
                    </li>
                  </ul>
                </div>
              </div>

              <Button
                onClick={handleJoin}
                className="group relative w-full h-[74px] rounded-[24px] overflow-hidden border border-orange-200/20 bg-gradient-to-b from-orange-400 via-orange-500 to-red-600 text-white font-black text-lg tracking-tight shadow-[0_8px_0_rgba(120,53,15,0.98),0_16px_28px_rgba(0,0,0,0.35)] active:translate-y-[4px] active:shadow-[0_3px_0_rgba(120,53,15,0.98),0_8px_14px_rgba(0,0,0,0.28)] transition-all"
              >
                <div className="absolute inset-x-4 top-2 h-1/3 rounded-full bg-white/20 blur-md" />
                <div className="absolute left-0 top-0 h-full w-20 -skew-x-12 bg-white/10" />
                <div className="absolute right-5 top-0 h-full w-10 -skew-x-12 bg-yellow-200/10" />
                <div className="relative flex items-center justify-center gap-3">
                  <div className="w-11 h-11 rounded-2xl bg-gradient-to-b from-red-700 via-red-800 to-red-950 border border-white/15 flex items-center justify-center shadow-[inset_0_1px_0_rgba(255,255,255,0.12),0_4px_10px_rgba(0,0,0,0.28)]">
                    <Swords className="w-5 h-5 text-white" />
                  </div>
                  <div className="text-center">
                    <p className="text-[24px] leading-none font-black [text-shadow:_0_2px_0_rgba(120,53,15,0.95),_0_4px_10px_rgba(0,0,0,0.35)]">
                      시작하기
                    </p>
                    <p className="text-[10px] mt-1 tracking-[0.22em] uppercase text-yellow-100/90">
                      
                    </p>
                  </div>
                </div>
              </Button>
            </motion.div>
          ) : (
            <motion.div
              key="active"
              initial={false}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.12 }}
              className="mb-4"
            >
              {/* 타이머 패널 */}
              <div className="grid grid-cols-1 gap-3 mb-4">
                <div className="relative rounded-[26px] p-[1px] bg-gradient-to-b from-red-300/25 to-white/5">
                  <div className="relative overflow-hidden rounded-[25px] border border-red-300/10 bg-[linear-gradient(to_bottom,_rgba(255,106,0,0.14),_rgba(255,255,255,0.04))] p-4 text-center">
                    <div className="absolute inset-x-4 top-2 h-10 rounded-full bg-white/10 blur-lg" />
                    <p className="text-[10px] uppercase tracking-[0.2em] text-white/45 font-bold mb-2">
                      Weekly Season Ends In
                    </p>
                    <div className="flex items-center justify-center gap-2">
                      <div className="w-9 h-9 rounded-xl bg-gradient-to-b from-red-500 to-orange-500 flex items-center justify-center shadow-[0_4px_0_rgba(120,53,15,0.9)]">
                        <Timer className="w-4 h-4 text-white" />
                      </div>
                      <span className="text-[28px] font-black font-mono text-white tracking-wider [text-shadow:_0_2px_0_rgba(0,0,0,0.45)]">
                        {countdown}
                      </span>
                    </div>
                    <p className="text-[10px] text-white/40 mt-2">매주 월요일 자정 초기화</p>
                  </div>
                </div>

                <div className="relative rounded-[26px] p-[1px] bg-gradient-to-b from-violet-300/20 to-white/5">
                  <div className="relative overflow-hidden rounded-[25px] border border-violet-300/10 bg-[linear-gradient(to_bottom,_rgba(147,51,234,0.14),_rgba(255,255,255,0.04))] p-4 text-center">
                    <div className="absolute inset-x-4 top-2 h-10 rounded-full bg-white/10 blur-lg" />
                    <p className="text-[10px] uppercase tracking-[0.2em] text-white/45 font-bold mb-2">
                      Season Score Ends In
                    </p>
                    <div className="flex items-center justify-center gap-2">
                      <div className="w-9 h-9 rounded-xl bg-gradient-to-b from-violet-500 to-fuchsia-600 flex items-center justify-center shadow-[0_4px_0_rgba(91,33,182,0.9)]">
                        <Timer className="w-4 h-4 text-white" />
                      </div>
                      <span className="text-[28px] font-black font-mono text-white tracking-wider [text-shadow:_0_2px_0_rgba(0,0,0,0.45)]">
                        {scoreCountdown}
                      </span>
                    </div>
                    <p className="text-[10px] text-white/40 mt-2">
                      2달 시즌 종료 후 순위 보상 지급
                    </p>
                  </div>
                </div>
              </div>

              {/* 탭 */}
              <div className="grid grid-cols-2 gap-2 mb-3">
                {(['weekly', 'season'] as const).map((tab) => {
                  const active = activeRankTab === tab;

                  return (
                    <button
                      key={tab}
                      onClick={() => setActiveRankTab(tab)}
                      className={`relative overflow-hidden rounded-2xl py-3 text-xs font-black tracking-wide transition-all ${
                        active
                          ? tab === 'weekly'
                            ? 'border border-orange-200/20 bg-gradient-to-b from-orange-400/80 via-orange-500/80 to-red-600/90 text-white shadow-[0_5px_0_rgba(120,53,15,0.92),0_10px_18px_rgba(0,0,0,0.22)]'
                            : 'border border-violet-200/20 bg-gradient-to-b from-violet-500/85 via-fuchsia-500/80 to-purple-700/90 text-white shadow-[0_5px_0_rgba(91,33,182,0.92),0_10px_18px_rgba(0,0,0,0.22)]'
                          : 'border border-white/10 bg-white/[0.04] text-white/55'
                      }`}
                    >
                      {active && (
                        <div className="absolute inset-x-3 top-1 h-1/3 rounded-full bg-white/15 blur-md" />
                      )}

                      <span className="relative">
                        {tab === 'weekly' ? '주간 걸음수 랭킹' : '시즌 점수 랭킹'}
                      </span>
                    </button>
                  );
                })}
              </div>

              {/* 랭킹 */}
              <div
                className={`relative rounded-[32px] p-[1.5px] ${
                  activeRankTab === 'weekly'
                    ? 'bg-gradient-to-b from-orange-300/30 via-red-300/12 to-white/5'
                    : 'bg-gradient-to-b from-violet-300/30 via-fuchsia-300/12 to-white/5'
                }`}
              >
                <div
                  className={`overflow-hidden rounded-[30px] border backdrop-blur-md shadow-[0_10px_30px_rgba(0,0,0,0.22)] ${
                    activeRankTab === 'weekly'
                      ? 'border-orange-200/10 bg-[linear-gradient(to_bottom,_rgba(255,145,77,0.10),_rgba(255,255,255,0.03))]'
                      : 'border-violet-200/10 bg-[linear-gradient(to_bottom,_rgba(168,85,247,0.12),_rgba(255,255,255,0.03))]'
                  }`}
                >
                  {activeRankTab === 'weekly' ? (
                    <>
                      <div className="px-4 pt-4 pb-3 border-b border-orange-200/10 bg-gradient-to-r from-orange-500/18 to-red-500/10">
                        <div className="flex items-center justify-between gap-3 mb-3">
                          <div>
                            <p className="text-[10px] text-orange-100/60 font-bold tracking-[0.18em] uppercase">Ranking Board</p>
                            <h3 className="text-sm font-black text-white">{getDisplayRankingTitle('weekly', weeklyRanking.length)}</h3>
                          </div>
                          <span className="text-[10px] text-white/45 font-semibold">Samsung Health 동기화가 필요합니다.</span>
                        </div>

                        <div className="rounded-[22px] border border-violet-200/20 bg-gradient-to-r from-violet-500/20 to-fuchsia-500/10 px-4 py-4 shadow-[0_4px_0_rgba(0,0,0,0.14)]">
                          <div className="flex items-center gap-3 mb-2">
                            <div className="min-w-[52px] h-9 px-3 rounded-xl bg-gradient-to-b from-violet-500 to-fuchsia-600 flex items-center justify-center text-[11px] font-black text-white shadow-[0_3px_0_rgba(91,33,182,0.9)]">
                              {myWeeklyRank ? `${myWeeklyRank}위` : '-'}
                            </div>
                            <div className="min-w-0 flex-1">
                              <p className="text-[10px] text-violet-100/55 font-bold tracking-[0.16em] uppercase">내 순위</p>
                              <p className="text-sm font-black text-violet-100 truncate">{myGameNickname || nickname || '나'}</p>
                            </div>
                            <div className="text-right">
                              <p className="text-[10px] text-white/45 font-bold">걸음수</p>
                              <p className="text-sm font-black text-white font-mono">{mySteps === 0 ? '-' : mySteps.toLocaleString()}</p>
                            </div>
                          </div>
                        </div>
                      </div>

                      <div className="grid grid-cols-[72px_minmax(0,1fr)_96px] items-center gap-3 px-4 py-4 bg-gradient-to-r from-orange-500/18 to-red-500/10 border-b border-orange-200/10 text-[10px] text-orange-100/70 font-bold tracking-[0.14em]">
                        <span className="pl-5">순위</span>
                        <span className="pl-2.5">닉네임</span>
                        <span className="text-right pr-1">걸음수</span>
                      </div>

                      {weeklyRanking.length === 0 ? (
                        <div className="py-10 text-center text-sm text-slate-400">
                          아직 주간 랭킹 데이터가 없습니다.
                        </div>
                      ) : (
                        <div className={RANKING_SCROLL_CLASS}>
                          {weeklyRanking.map((item, idx) => (
                            <motion.div
                              key={item.rank}
                              initial={{ opacity: 0, x: -10 }}
                              animate={{ opacity: 1, x: 0 }}
                              transition={{ delay: idx * 0.02 }}
                              className={`mx-2 my-2 grid grid-cols-[72px_minmax(0,1fr)_96px] items-center gap-3 rounded-[22px] border px-4 py-4 bg-gradient-to-r shadow-[0_4px_0_rgba(0,0,0,0.14)] ${getRankAccent(item.rank, 'weekly')}`}
                            >
                              <div className="flex justify-start">
                                <div
                                  className={`min-w-[44px] h-8 px-2 rounded-xl flex items-center justify-center text-[11px] font-black shadow-[0_3px_0_rgba(0,0,0,0.22)] ${
                                    item.rank === 1
                                      ? 'bg-gradient-to-b from-yellow-300 to-yellow-500 text-white'
                                      : item.rank === 2
                                      ? 'bg-gradient-to-b from-slate-200 to-slate-500 text-white'
                                      : item.rank === 3
                                      ? 'bg-gradient-to-b from-orange-300 to-amber-700 text-white'
                                      : 'bg-white/[0.05] border border-white/10 text-white/70'
                                  }`}
                                >
                                  {item.rank}위
                                </div>
                              </div>

                              <span className="min-w-0 text-xs font-bold text-white truncate">
                                {item.nickname}
                              </span>

                              <span className="text-right text-xs text-white/85 font-mono font-bold">
                                {item.steps.toLocaleString()}
                              </span>
                            </motion.div>
                          ))}
                        </div>
                      )}
                    </>
                  ) : (
                    <>
                      <div className="px-4 pt-4 pb-3 border-b border-violet-200/10 bg-gradient-to-r from-violet-500/18 to-fuchsia-500/10">
                        <div className="flex items-center justify-between gap-3 mb-3">
                          <div>
                            <p className="text-[10px] text-violet-100/60 font-bold tracking-[0.18em] uppercase">Ranking Board</p>
                            <h3 className="text-sm font-black text-white">{getDisplayRankingTitle('season', seasonRanking.length)}</h3>
                          </div>
                          <span className="text-[10px] text-white/45 font-semibold">티어와 점수는 시즌이 끝나도 유지됩니다.</span>
                        </div>

                        <div className="rounded-[22px] border border-violet-200/20 bg-gradient-to-r from-violet-500/20 to-fuchsia-500/10 px-4 py-4 shadow-[0_4px_0_rgba(0,0,0,0.14)]">
                          <div className="flex items-center gap-3 mb-2">
                            <div className="min-w-[52px] h-9 px-3 rounded-xl bg-gradient-to-b from-violet-500 to-fuchsia-600 flex items-center justify-center text-[11px] font-black text-white shadow-[0_3px_0_rgba(91,33,182,0.9)]">
                              {mySeasonRank ? `${mySeasonRank}위` : '-'}
                            </div>
                            <div className="min-w-0 flex-1">
                              <p className="text-[10px] text-violet-100/55 font-bold tracking-[0.16em] uppercase">내 순위</p>
                              <p className="text-sm font-black text-violet-100 truncate">{myGameNickname || nickname || '나'}</p>
                            </div>
                            <div className="text-right">
                              <p className="text-[10px] text-white/45 font-bold">점수 / 티어</p>
                              <p className="text-sm font-black text-white font-mono">{myScore.toLocaleString()}</p>
                              <p className={`text-[10px] font-black ${myTier.textColor}`}>{myTier.name}</p>
                            </div>
                          </div>
                        </div>
                      </div>

                      <div className="grid grid-cols-[72px_minmax(0,1fr)_88px_72px] items-center gap-3 px-4 py-4 bg-gradient-to-r from-violet-500/18 to-fuchsia-500/10 border-b border-violet-200/10 text-[10px] text-violet-100/75 font-bold tracking-[0.14em]">
                        <span className="pl-5">순위</span>
                        <span className="pl-2.0">닉네임</span>
                        <span className="text-center translate-x-3">점수</span>
                        <span className="text-right pr-3">티어</span>
                      </div>

                      {seasonRanking.length === 0 ? (
                        <div className="py-10 text-center text-sm text-slate-400">
                          아직 시즌 랭킹 데이터가 없습니다.
                        </div>
                      ) : (
                        <div className={RANKING_SCROLL_CLASS}>
                          {seasonRanking.map((item, idx) => (
                            <motion.div
                              key={item.rank}
                              initial={{ opacity: 0, x: -10 }}
                              animate={{ opacity: 1, x: 0 }}
                              transition={{ delay: idx * 0.02 }}
                              className={`mx-2 my-2 grid grid-cols-[64px_minmax(0,1.4fr)_72px_60px] items-center gap-2 rounded-[22px] border px-4 py-4 bg-gradient-to-r shadow-[0_4px_0_rgba(0,0,0,0.14)] ${getRankAccent(item.rank, 'season')}`}
                            >
                              <div className="flex justify-start">
                                <div
                                  className={`min-w-[44px] h-8 px-2 rounded-xl flex items-center justify-center text-[11px] font-black shadow-[0_3px_0_rgba(0,0,0,0.22)] ${
                                    item.rank === 1
                                      ? 'bg-gradient-to-b from-yellow-300 to-yellow-500 text-white'
                                      : item.rank === 2
                                      ? 'bg-gradient-to-b from-slate-200 to-slate-500 text-white'
                                      : item.rank === 3
                                      ? 'bg-gradient-to-b from-orange-300 to-amber-700 text-white'
                                      : 'bg-white/[0.05] border border-white/10 text-white/70'
                                  }`}
                                >
                                  {item.rank}위
                                </div>
                              </div>

                              <span className="min-w-0 text-xs font-bold text-white truncate">
                                {item.nickname}
                              </span>

                              <span className="text-center text-xs text-white/85 font-mono font-bold">
                                {item.score.toLocaleString()}
                              </span>

                              <span className="text-right text-[10px] font-black text-yellow-300">
                                {item.tier}
                              </span>
                            </motion.div>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>

            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* 경고 다이얼로그 */}
      <AlertDialog open={showWarning} onOpenChange={setShowWarning}>
        <AlertDialogContent className="bg-[#171225] border-white/10 text-white">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-white flex items-center gap-2 font-black">
              <Timer className="w-5 h-5 text-orange-400" />
              시즌 종료 임박!
            </AlertDialogTitle>
            <AlertDialogDescription className="text-white/70">
              이번 시즌이 <strong className="text-orange-400">{daysRemaining}일</strong> 남았습니다.
              <br />
              지금 시작하시겠습니까?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-white/10 border-white/20 text-white hover:bg-white/20">
              다음 시즌에!
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                try {
                  const result = await weekWalkApi.join();

                  await syncGameStateAndShowOwnAchievements(result.new_achievement_codes);

                  toast.success(result.message || 'Week Walk 경쟁전에 참여했습니다.');
                  setShowWarning(false);
                  await loadOverview();
                } catch (error: any) {
                  console.error('Week Walk 참가 실패:', error);
                  toast.error(error?.message || '경쟁전 참여에 실패했습니다.');
                }
              }}
              className="bg-gradient-to-r from-red-600 to-orange-600 text-white border-0"
            >
              할래요!
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

export default WeekWalkPage;