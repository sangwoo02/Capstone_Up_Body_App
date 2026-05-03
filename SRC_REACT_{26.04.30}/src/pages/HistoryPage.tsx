/**
 * 📊 활동 히스토리 페이지
 * 
 * 일주일치 걸음 수, 활동 칼로리 그래프와
 * 몸무게 변동 그래프를 표시합니다.
 */

import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Footprints, Flame, Scale, TrendingUp, Lock, HelpCircle, AlertTriangle, ChevronLeft, ChevronRight } from 'lucide-react';
import { Popover, PopoverTrigger, PopoverContent } from '@/components/ui/popover';
import { useAppStore } from '@/stores/appStore';
import AppLayout from '@/components/AppLayout';
import { toast } from 'sonner';
import { useRnBridge } from '@/hooks/useRnBridge';

// 주어진 날짜가 속한 주의 월요일을 반환
const getMonday = (date: Date) => {
  const d = new Date(date);
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  d.setDate(diff);
  d.setHours(0, 0, 0, 0);
  return d;
};

// 월요일부터 일요일까지 7일 배열 반환
const getWeekDays = (monday: Date) => {
  const days = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    days.push(d);
  }
  return days;
};

const formatLocalDate = (date: Date) => {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
};

const HistoryPage = () => {
  const navigate = useNavigate();
  const {
    activityHistory,
    weightHistory,
    hasInBodySynced,
    setActivityHistory,
    setWeightHistory,
  } = useAppStore();

  const { rnRequest } = useRnBridge();
  const [isLoading, setIsLoading] = useState(false);

  // 현재 보고있는 주의 월요일 (기본: 이번 주)
  const [currentMonday, setCurrentMonday] = useState(() => getMonday(new Date()));

  const weekDays = getWeekDays(currentMonday);
  const sunday = weekDays[6];
  const weekStart = formatLocalDate(currentMonday);
  const weekEnd = formatLocalDate(sunday);

  // 백엔드에서 히스토리 데이터 가져오기
  useEffect(() => {
    const fetchHistory = async () => {
      if (!hasInBodySynced) return;

      const token = localStorage.getItem("access_token");
      if (!token) return;

      setIsLoading(true);

      try {
        const result = await rnRequest("HEALTHCARE_HISTORY_REQUEST", {
          token,
          week_start: weekStart,
          week_end: weekEnd,
        });

        setActivityHistory(result?.activity_history || []);
        setWeightHistory(result?.weight_history || []);
      } catch (e: any) {
        toast.error(e?.message ? String(e.message) : "히스토리 불러오기에 실패했습니다.");
      } finally {
        setIsLoading(false);
      }
    };

    fetchHistory();
  }, [hasInBodySynced, currentMonday, weekStart, weekEnd]);

  const isCurrentWeek = getMonday(new Date()).getTime() === currentMonday.getTime();

  const goToPrevWeek = () => {
    const prev = new Date(currentMonday);
    prev.setDate(prev.getDate() - 7);
    setCurrentMonday(prev);
  };

  const goToNextWeek = () => {
    if (isCurrentWeek) return;
    const next = new Date(currentMonday);
    next.setDate(next.getDate() + 7);
    setCurrentMonday(next);
  };

  // 주간 날짜 범위 포맷
  const formatWeekRange = () => {
    const monYear = currentMonday.getFullYear();
    const sunYear = sunday.getFullYear();
    const mon = `${currentMonday.getMonth() + 1}.${currentMonday.getDate()}`;
    const sun = `${sunday.getMonth() + 1}.${sunday.getDate()}`;
    if (monYear !== sunYear) {
      return `${monYear}.${mon} - ${sunYear}.${sun}`;
    }
    return `${monYear}.${mon} - ${sun}`;
  };

  const getActivityForDate = (date: Date) => {
    const dateStr = formatLocalDate(date);
    return activityHistory.find(a => a.date === dateStr) || { date: dateStr, steps: 0, calories: 0 };
  };

  const weeklyData = weekDays.map(d => {
    const activity = getActivityForDate(d);
    return {
      dateObj: d,
      label: `${d.getMonth() + 1}/${d.getDate()}`,
      dayLabel: ['일', '월', '화', '수', '목', '금', '토'][d.getDay()],
      steps: activity.steps,
      calories: activity.calories,
    };
  });

  const today = new Date();
  const todayStr = formatLocalDate(today);

  const maxSteps = Math.max(...weeklyData.map(d => d.steps), 1);
  const maxCalories = Math.max(...weeklyData.map(d => d.calories), 1);

  // 몸무게 변동 데이터 (최근 10개까지)
  const recentWeightHistory = weightHistory.slice(-10);

  const totalSteps = weeklyData.reduce((sum, d) => sum + d.steps, 0);
  const totalCalories = weeklyData.reduce((sum, d) => sum + d.calories, 0);
  const avgSteps = Math.round(totalSteps / 7);
  const avgCalories = Math.round(totalCalories / 7);

  // 몸무게 그래프 Y축 고정값
  const yAxisValues = [120, 100, 80, 60, 40, 20];
  const graphHeight = 120; // SVG viewBox height

  // 삼성 헬스 미연동 시 전체 잠금 오버레이
  if (!hasInBodySynced) {
    return (
      <AppLayout>
        {/* Header */}
        <div className="gradient-primary px-6 pt-safe-top pb-6">
          <div className="flex items-center gap-3 pt-3">
            <button
              onClick={() => navigate('/inbody')}
              className="w-10 h-10 rounded-xl bg-primary-foreground/10 flex items-center justify-center"
            >
              <ArrowLeft className="w-5 h-5 text-primary-foreground" />
            </button>
            <h1 className="text-xl font-bold text-primary-foreground flex-1">활동 히스토리</h1>
            <Popover>
              <PopoverTrigger asChild>
                <button className="w-8 h-8 rounded-lg bg-primary-foreground/10 flex items-center justify-center">
                  <HelpCircle className="w-4 h-4 text-primary-foreground/70" />
                </button>
              </PopoverTrigger>
              <PopoverContent className="w-72 text-sm p-0 overflow-hidden" side="bottom" align="end">
                <div className="px-4 py-3">
                  <div className="flex items-center gap-2 mb-1.5">
                    <div className="w-5 h-5 rounded-full bg-warning/20 flex items-center justify-center">
                      <AlertTriangle className="w-3 h-3 text-warning" />
                    </div>
                    <p className="text-warning font-semibold text-xs">
                      Samsung Health 앱 연동 안내
                    </p>
                  </div>

                  <p className="text-warning-foreground/80 text-[11px] leading-relaxed">
                    활동 히스토리를 사용하시려면 Samsung Health 앱 연동이 필요합니다. 
                    "프로필 → 신체 정보 입력 → Samsung Health 앱 연동"을 진행해주세요.
                  </p>
                </div>
              </PopoverContent>
            </Popover>
          </div>
        </div>

        <div className="px-6 py-4 space-y-5">
          {/* 잠금된 주간 요약 */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-muted/50 rounded-2xl p-4 relative overflow-hidden">
              <div className="flex items-center gap-2 mb-1 opacity-50">
                <Footprints className="w-4 h-4 text-muted-foreground" />
                <span className="text-xs text-muted-foreground">주간 평균 걸음</span>
              </div>
              <span className="text-xl font-bold text-muted-foreground opacity-50">---</span>
              <div className="absolute inset-0 flex items-center justify-center bg-background/60">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Lock className="w-4 h-4" />
                  <span className="text-xs">삼성 헬스 연동 필요</span>
                </div>
              </div>
            </div>
            <div className="bg-muted/50 rounded-2xl p-4 relative overflow-hidden">
              <div className="flex items-center gap-2 mb-1 opacity-50">
                <Flame className="w-4 h-4 text-muted-foreground" />
                <span className="text-xs text-muted-foreground">주간 평균 칼로리</span>
              </div>
              <span className="text-xl font-bold text-muted-foreground opacity-50">---</span>
              <div className="absolute inset-0 flex items-center justify-center bg-background/60">
                <div className="flex items-center gap-2 text-muted-foreground">
                  <Lock className="w-4 h-4" />
                  <span className="text-xs">삼성 헬스 연동 필요</span>
                </div>
              </div>
            </div>
          </div>

          {/* 잠금된 걸음 수 그래프 */}
          <div className="bg-muted/50 rounded-2xl p-5 relative overflow-hidden" style={{ minHeight: '200px' }}>
            <div className="flex items-center gap-2 mb-5 opacity-50">
              <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center">
                <Footprints className="w-4 h-4 text-muted-foreground" />
              </div>
              <h2 className="text-sm font-semibold text-muted-foreground">일주일 걸음 수</h2>
            </div>
            <div className="h-32 opacity-50" />
            <div className="absolute inset-0 flex items-center justify-center bg-background/60">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Lock className="w-4 h-4" />
                <span className="text-xs">삼성 헬스 연동 필요</span>
              </div>
            </div>
          </div>

          {/* 잠금된 활동 칼로리 그래프 */}
          <div className="bg-muted/50 rounded-2xl p-5 relative overflow-hidden" style={{ minHeight: '200px' }}>
            <div className="flex items-center gap-2 mb-5 opacity-50">
              <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center">
                <Flame className="w-4 h-4 text-muted-foreground" />
              </div>
              <h2 className="text-sm font-semibold text-muted-foreground">일주일 활동 칼로리</h2>
            </div>
            <div className="h-32 opacity-50" />
            <div className="absolute inset-0 flex items-center justify-center bg-background/60">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Lock className="w-4 h-4" />
                <span className="text-xs">삼성 헬스 연동 필요</span>
              </div>
            </div>
          </div>

          {/* 잠금된 몸무게 변동 그래프 */}
          <div className="bg-muted/50 rounded-2xl p-5 relative overflow-hidden" style={{ minHeight: '200px' }}>
            <div className="flex items-center gap-2 mb-4 opacity-50">
              <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center">
                <Scale className="w-4 h-4 text-muted-foreground" />
              </div>
              <h2 className="text-sm font-semibold text-muted-foreground">몸무게 변동</h2>
            </div>
            <div className="h-32 opacity-50" />
            <div className="absolute inset-0 flex items-center justify-center bg-background/60">
              <div className="flex items-center gap-2 text-muted-foreground">
                <Lock className="w-4 h-4" />
                <span className="text-xs">삼성 헬스 연동 필요</span>
              </div>
            </div>
          </div>
        </div>
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      {/* Header */}
      <div className="gradient-primary px-6 pt-safe-top pb-6">
        <div className="flex items-center gap-3 pt-3">
          <button
            onClick={() => navigate('/inbody')}
            className="w-10 h-10 rounded-xl bg-primary-foreground/10 flex items-center justify-center"
          >
            <ArrowLeft className="w-5 h-5 text-primary-foreground" />
          </button>
          <h1 className="text-xl font-bold text-primary-foreground flex-1">활동 히스토리</h1>
            <Popover>
              <PopoverTrigger asChild>
                <button className="w-8 h-8 rounded-lg bg-primary-foreground/10 flex items-center justify-center">
                  <HelpCircle className="w-4 h-4 text-primary-foreground/70" />
                </button>
              </PopoverTrigger>
              <PopoverContent className="w-80 text-sm p-0 overflow-hidden" side="bottom" align="end">
                <div className="bg-warning/10 border-b border-warning/20 px-4 py-3">
                  <div className="flex items-center gap-2 mb-1.5">
                    <div className="w-5 h-5 rounded-full bg-warning/20 flex items-center justify-center">
                      <AlertTriangle className="w-3 h-3 text-warning" />
                    </div>
                    <p className="text-warning font-semibold text-xs">동기화 안내</p>
                  </div>
                  <p className="text-warning-foreground/80 text-[11px] leading-relaxed">
                    활동을 마친 후 동기화가 되지 않았다면 수동으로 진행해야 합니다.<span className="font-semibold text-warning"> "프로필 → Samsung Health 동기화 갱신"</span>을 진행해주세요.
                  </p>
                </div>
                <div className="px-4 py-3 space-y-3">
                  <div>
                    <p className="text-foreground font-medium mb-1.5 text-xs">주간 평균 표시 안내</p>
                    <p className="text-muted-foreground text-[11px] leading-relaxed">
                      주간 평균 걸음과 평균 칼로리는 선택된 주(월요일~일요일)의 데이터를 기준으로 평균 값을 계산하여 표시합니다.
                    </p>
                  </div>
                  <div>
                    <p className="text-foreground font-medium mb-1.5 text-xs">활동 기록 안내</p>
                    <p className="text-muted-foreground text-[11px] leading-relaxed">
                      이 그래프는 선택한 주(월요일~일요일)의 활동 기록을 보여줍니다. Health Connect가 Health Care앱에 연동된 날부터 기록이 표시되며 상단의 &lt; &gt; 버튼을 통해 히스토리 기록을 확인할 수 있습니다.
                    </p>
                  </div>
                </div>
              </PopoverContent>
            </Popover>
        </div>
      </div>

      <div className="px-6 py-4 space-y-5">
        {/* 주간 네비게이션 */}
        <div className="flex items-center justify-between">
          <button onClick={goToPrevWeek} className="w-9 h-9 rounded-xl bg-card card-shadow flex items-center justify-center">
            <ChevronLeft className="w-5 h-5 text-foreground" />
          </button>
          <span className="text-sm font-semibold text-foreground">{formatWeekRange()}</span>
          <button
            onClick={goToNextWeek}
            disabled={isCurrentWeek}
            className={`w-9 h-9 rounded-xl bg-card card-shadow flex items-center justify-center ${isCurrentWeek ? 'opacity-30' : ''}`}
          >
            <ChevronRight className="w-5 h-5 text-foreground" />
          </button>
        </div>

        {/* 주간 요약 */}
        <motion.div
          key={currentMonday.toISOString()}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="grid grid-cols-2 gap-3"
        >
          <div className="bg-card rounded-2xl p-4 card-shadow">
            <div className="flex items-center gap-2 mb-1">
              <Footprints className="w-4 h-4 text-primary" />
              <span className="text-xs text-muted-foreground">주간 평균 걸음</span>
            </div>
            <span className="text-xl font-bold text-foreground">{avgSteps.toLocaleString()}</span>
            <span className="text-xs text-muted-foreground ml-1">걸음</span>
          </div>
          <div className="bg-card rounded-2xl p-4 card-shadow">
            <div className="flex items-center gap-2 mb-1">
              <Flame className="w-4 h-4 text-destructive" />
              <span className="text-xs text-muted-foreground">주간 평균 칼로리</span>
            </div>
            <span className="text-xl font-bold text-foreground">{avgCalories.toLocaleString()}</span>
            <span className="text-xs text-muted-foreground ml-1">kcal</span>
          </div>
        </motion.div>

        {/* 걸음 수 그래프 */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="bg-card rounded-2xl p-5 card-shadow"
        >
          <div className="flex items-center gap-2 mb-5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary/20 to-info/15 flex items-center justify-center">
              <Footprints className="w-4 h-4 text-primary" />
            </div>
            <h2 className="text-sm font-semibold text-foreground">일주일 걸음 수</h2>
          </div>

          <div className="flex items-end gap-2 h-52">
            {weeklyData.map((day, i) => {
              const heightPercent = maxSteps > 0 ? (day.steps / maxSteps) * 100 : 0;
              const isToday = formatLocalDate(day.dateObj) === todayStr;
              return (
                <div key={day.label} className="flex-1 flex flex-col items-center gap-1">
                  <span className="text-[10px] text-muted-foreground font-medium">
                    {day.steps > 0 ? (day.steps >= 1000 ? `${(day.steps / 1000).toFixed(1)}k` : day.steps) : ''}
                  </span>
                  <div className="w-full flex items-end" style={{ height: '160px' }}>
                    <motion.div
                      initial={{ height: 0 }}
                      animate={{ height: `${Math.max(heightPercent, 4)}%` }}
                      transition={{ delay: 0.2 + i * 0.05, duration: 0.5 }}
                      className={`w-full rounded-t-lg ${
                        isToday
                          ? 'bg-gradient-to-t from-primary to-primary/70'
                          : day.steps > 0
                            ? 'bg-primary/30'
                            : 'bg-muted'
                      }`}
                    />
                  </div>
                  <span className={`text-[10px] font-medium ${isToday ? 'text-primary' : 'text-muted-foreground'}`}>
                    {day.dayLabel}
                  </span>
                  <span className={`text-[9px] ${isToday ? 'text-primary/70' : 'text-muted-foreground/60'}`}>
                    {day.label}
                  </span>
                </div>
              );
            })}
          </div>
        </motion.div>

        {/* 활동 칼로리 그래프 */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="bg-card rounded-2xl p-5 card-shadow"
        >
          <div className="flex items-center gap-2 mb-5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-destructive/20 to-warning/15 flex items-center justify-center">
              <Flame className="w-4 h-4 text-destructive" />
            </div>
            <h2 className="text-sm font-semibold text-foreground">일주일 활동 칼로리</h2>
          </div>

          <div className="flex items-end gap-2 h-52">
            {weeklyData.map((day, i) => {
              const heightPercent = maxCalories > 0 ? (day.calories / maxCalories) * 100 : 0;
              const isToday = formatLocalDate(day.dateObj) === todayStr;
              return (
                <div key={day.label} className="flex-1 flex flex-col items-center gap-1">
                  <span className="text-[10px] text-muted-foreground font-medium">
                    {day.calories > 0 ? day.calories : ''}
                  </span>
                  <div className="w-full flex items-end" style={{ height: '160px' }}>
                    <motion.div
                      initial={{ height: 0 }}
                      animate={{ height: `${Math.max(heightPercent, 4)}%` }}
                      transition={{ delay: 0.2 + i * 0.05, duration: 0.5 }}
                      className={`w-full rounded-t-lg ${
                        isToday
                          ? 'bg-gradient-to-t from-destructive to-destructive/70'
                          : day.calories > 0
                            ? 'bg-destructive/30'
                            : 'bg-muted'
                      }`}
                    />
                  </div>
                  <span className={`text-[10px] font-medium ${isToday ? 'text-destructive' : 'text-muted-foreground'}`}>
                    {day.dayLabel}
                  </span>
                  <span className={`text-[9px] ${isToday ? 'text-destructive/70' : 'text-muted-foreground/60'}`}>
                    {day.label}
                  </span>
                </div>
              );
            })}
          </div>
        </motion.div>

        {/* 몸무게 변동 그래프 */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="bg-card rounded-2xl p-5 card-shadow"
        >
          <div className="flex items-center gap-2 mb-4">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-info/20 to-primary/15 flex items-center justify-center">
              <Scale className="w-4 h-4 text-info" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-foreground">몸무게 변동</h2>
              <p className="text-[10px] text-muted-foreground">변동이 있을 때만 기록됩니다</p>
            </div>
          </div>

          {recentWeightHistory.length > 1 ? (
            <WeightGraph recentWeightHistory={recentWeightHistory} yAxisValues={yAxisValues} graphHeight={graphHeight} />
          ) : (
            <div className="h-32 flex items-center justify-center">
              <div className="text-center">
                <TrendingUp className="w-8 h-8 text-muted-foreground/40 mx-auto mb-2" />
                <p className="text-sm text-muted-foreground">
                  {recentWeightHistory.length === 1
                    ? '몸무게 변동이 기록되면 그래프가 표시됩니다'
                    : '몸무게 데이터가 없습니다'}
                </p>
              </div>
            </div>
          )}
        </motion.div>
      </div>
    </AppLayout>
  );
};

// 몸무게 그래프 컴포넌트
interface WeightGraphProps {
  recentWeightHistory: { weight: number; recordedAt: string }[];
  yAxisValues: number[];
  graphHeight: number;
}

const WeightGraph = ({ recentWeightHistory, yAxisValues, graphHeight }: WeightGraphProps) => {
  const paddingX = 20;
  const svgWidth = Math.max(recentWeightHistory.length * 50, 200);
  const drawableWidth = svgWidth - paddingX * 2;
  const yMax = 120;
  const yMin = 0;

  const getY = (weight: number) => {
    const clamped = Math.min(Math.max(weight, yMin), yMax);
    return graphHeight - ((clamped - yMin) / (yMax - yMin)) * graphHeight;
  };

  const getX = (i: number) => {
    return paddingX + i * (drawableWidth / Math.max(recentWeightHistory.length - 1, 1));
  };

  return (
    <div className="relative h-52">
      {/* Y축 레이블 */}
      <div className="absolute left-0 top-0 bottom-6 w-8 flex flex-col justify-between">
        {yAxisValues.map(v => (
          <span key={v} className="text-[10px] text-muted-foreground text-right pr-1">{v}</span>
        ))}
      </div>

      {/* 그래프 영역 */}
      <div className="ml-10 h-full flex flex-col overflow-hidden">
        <svg className="w-full flex-1" viewBox={`0 0 ${svgWidth} ${graphHeight}`} preserveAspectRatio="xMidYMid meet">
          {/* 가로 그리드 라인 */}
          {yAxisValues.map(v => {
            const y = getY(v);
            return (
              <line key={v} x1="0" y1={y} x2={svgWidth} y2={y} stroke="hsl(var(--border))" strokeWidth="1" strokeDasharray="4 3" opacity="0.7" />
            );
          })}

          {/* 라인 그래프 */}
          <motion.polyline
            initial={{ pathLength: 0, opacity: 0 }}
            animate={{ pathLength: 1, opacity: 1 }}
            transition={{ duration: 1, delay: 0.5 }}
            fill="none"
            stroke="hsl(var(--primary))"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            points={recentWeightHistory.map((w, i) => `${getX(i)},${getY(w.weight)}`).join(' ')}
          />

          {/* 데이터 포인트 */}
          {recentWeightHistory.map((w, i) => (
            <motion.circle
              key={i}
              initial={{ r: 0 }}
              animate={{ r: 4 }}
              transition={{ delay: 0.6 + i * 0.1 }}
              cx={getX(i)}
              cy={getY(w.weight)}
              fill="hsl(var(--primary))"
              stroke="hsl(var(--card))"
              strokeWidth="2"
            />
          ))}
        </svg>

        {/* X축: 몸무게 값 (kg) */}
        <div className="flex mt-1.5" style={{ paddingLeft: `${(paddingX / svgWidth) * 100}%`, paddingRight: `${(paddingX / svgWidth) * 100}%` }}>
          {recentWeightHistory.map((w, i) => (
            <span
              key={i}
              className="text-[9px] text-muted-foreground text-center"
              style={{ width: `${100 / Math.max(recentWeightHistory.length - 1, 1)}%`, marginLeft: i === 0 ? '-1em' : undefined, marginRight: i === recentWeightHistory.length - 1 ? '-1em' : undefined }}
            >
              {w.weight.toFixed(1)}kg
            </span>
          ))}
        </div>
      </div>
    </div>
  );
};

export default HistoryPage;
