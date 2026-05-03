/**
 * 📊 신체 분석 페이지 (백엔드 통합)
 *
 * 기존 UI 유지 + rnRequest를 통한 실시간 데이터 fetch + 공공데이터 평균 비교
 * History 아이콘은 유지
 */

import { useState, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useLocation, useNavigate } from 'react-router-dom';
import {
  TrendingUp,
  TrendingDown,
  Minus,
  History,
  Scale,
  Ruler,
  Heart,
  Droplets,
  Flame,
  Footprints,
  Activity,
  Target,
  Lock,
  Check,
  Loader2,
  Gamepad2,
  Sparkles,
  Zap,
  HelpCircle,
} from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import { useRnBridge } from '@/hooks/useRnBridge';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import AppLayout from '@/components/AppLayout';
import { toast } from 'sonner';

const calculateAge = (birthDate: string): number => {
  const today = new Date();
  const birth = new Date(birthDate);
  let age = today.getFullYear() - birth.getFullYear();
  const monthDiff = today.getMonth() - birth.getMonth();
  if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birth.getDate())) age--;
  return age;
};

const AVERAGE_CACHE_TTL = 7 * 24 * 60 * 60 * 1000;
const AVERAGE_CACHE_KEY_PREFIX = 'healthcare_average_cache_v6';

type AverageRange = { min: number; max: number; avg: number };

type CachedAverageData = {
  savedAt: number;
  data: {
    height: AverageRange;
    weight: AverageRange;
    body_fat: AverageRange;
    bmi: AverageRange;
  };
};

const getAverageAgeKey = (age?: number | null) => {
  if (!age || !Number.isFinite(age)) return 'unknown';

  // 공공데이터 API는 연령대가 아니라 실제 TEST_AGE 기준으로 호출한다.
  // 캐시도 실제 나이 기준으로 나눠야 생년월일 변경 후 이전 평균이 재사용되지 않는다.
  return String(Math.floor(age));
};

const getAverageCacheKey = ({
  userId,
  gender,
  age,
}: {
  userId?: string | number;
  gender?: string | null;
  age?: number | null;
}) => {
  const accountKey = userId?.toString() || 'anonymous';
  const genderKey = (gender || 'unknown').toLowerCase();
  const ageKey = getAverageAgeKey(age);

  return `${AVERAGE_CACHE_KEY_PREFIX}:${accountKey}:${genderKey}:${ageKey}`;
};

const readAverageCache = ({
  userId,
  gender,
  age,
}: {
  userId?: string | number;
  gender?: string | null;
  age?: number | null;
}): CachedAverageData | null => {
  try {
    const raw = localStorage.getItem(
      getAverageCacheKey({ userId, gender, age })
    );
    if (!raw) return null;

    const parsed = JSON.parse(raw) as CachedAverageData;

    if (!parsed || typeof parsed.savedAt !== 'number' || !parsed.data) {
      return null;
    }

    return parsed;
  } catch {
    return null;
  }
};

const writeAverageCache = (
  {
    userId,
    gender,
    age,
  }: {
    userId?: string | number;
    gender?: string | null;
    age?: number | null;
  },
  data: {
    height: AverageRange;
    weight: AverageRange;
    body_fat: AverageRange;
    bmi: AverageRange;
  }
) => {
  try {
    const payload: CachedAverageData = {
      savedAt: Date.now(),
      data,
    };

    localStorage.setItem(
      getAverageCacheKey({ userId, gender, age }),
      JSON.stringify(payload)
    );
  } catch {
    // localStorage 저장 실패 무시
  }
};

const isAverageCacheExpired = (savedAt: number) => {
  return Date.now() - savedAt > AVERAGE_CACHE_TTL;
};

interface MetricCardProps {
  label: string;
  value: string | number;
  unit: string;
  status?: 'good' | 'warning' | 'bad' | 'neutral';
  comparison?: { avgMin: number; avgMax: number; userValue: number };
  comparisonLabel?: string;
  reference?: { label: string; value?: number | null; unit?: string; isLoading?: boolean };
  icon: React.ElementType;
  delay?: number;
  showStatus?: boolean;
}

const MetricCard = ({
  label,
  value,
  unit,
  status = 'neutral',
  comparison,
  comparisonLabel = '평균',
  reference,
  icon: Icon,
  delay = 0,
  showStatus = true,
}: MetricCardProps) => {
  const statusColors = {
    good: 'text-success',
    warning: 'text-warning',
    bad: 'text-destructive',
    neutral: 'text-muted-foreground',
  };
  const statusLabels = {
    good: '정상',
    warning: '주의',
    bad: '위험',
    neutral: '-',
  };

  const usableComparison =
    comparison &&
    Number.isFinite(comparison.avgMin) &&
    Number.isFinite(comparison.avgMax) &&
    Number.isFinite(comparison.userValue) &&
    comparison.avgMax > comparison.avgMin &&
    comparison.avgMax > 0
      ? comparison
      : null;

  const hasReferenceValue =
    reference?.value !== null &&
    reference?.value !== undefined &&
    Number.isFinite(Number(reference.value)) &&
    Number(reference.value) > 0;

  const usableReference = reference && (reference.isLoading || hasReferenceValue) ? reference : null;

  const referenceDisplayValue =
    usableReference && hasReferenceValue && !usableReference.isLoading
      ? `${usableReference.value}${(usableReference.unit ?? unit) ? ` ${usableReference.unit ?? unit}` : ''}`
      : ' ';

  const getComparisonIcon = () => {
    if (!usableComparison) return null;
    const { avgMin, avgMax, userValue } = usableComparison;
    if (userValue < avgMin) return <TrendingDown className="w-4 h-4 text-warning" />;
    if (userValue > avgMax) return <TrendingUp className="w-4 h-4 text-warning" />;
    return <Minus className="w-4 h-4 text-success" />;
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay }}
      className="bg-card rounded-2xl p-4 card-shadow"
    >
      <div className="flex items-start justify-between mb-2">
        <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-primary/20 to-info/15 flex items-center justify-center">
          <Icon className="w-4 h-4 text-primary" />
        </div>

        {showStatus && status !== 'neutral' && (
          <div className={`flex items-center gap-1 ${statusColors[status]}`}>
            {getComparisonIcon()}
            <span className="text-xs font-medium">{statusLabels[status]}</span>
          </div>
        )}
      </div>

      <p className="text-xs text-muted-foreground">{label}</p>

      <div className="flex items-baseline gap-1 mt-0.5">
        <span className="text-xl font-bold text-foreground">{value}</span>
        <span className="text-xs text-muted-foreground">{unit}</span>
      </div>

      {usableComparison && (
        <div className="mt-2 pt-2 border-t border-border">
          <p className="text-[10px] text-muted-foreground">
            {comparisonLabel}: {usableComparison.avgMin} - {usableComparison.avgMax} {unit}
          </p>

          <div className="mt-1.5 h-1.5 bg-secondary rounded-full overflow-hidden relative">
            <div
              className="absolute h-full bg-success/30 rounded-full"
              style={{
                left: `${(usableComparison.avgMin / (usableComparison.avgMax * 1.5)) * 100}%`,
                width: `${((usableComparison.avgMax - usableComparison.avgMin) / (usableComparison.avgMax * 1.5)) * 100}%`,
              }}
            />
            <motion.div
              initial={{ left: 0 }}
              animate={{
                left: `${Math.min((usableComparison.userValue / (usableComparison.avgMax * 1.5)) * 100, 100)}%`,
              }}
              transition={{ delay: delay + 0.3, duration: 0.5 }}
              className="absolute w-2.5 h-2.5 -top-0.5 rounded-full gradient-primary border-2 border-card"
              style={{ transform: 'translateX(-50%)' }}
            />
          </div>

          {usableReference && (
            <div className="mt-2 pt-2 border-t border-border">
              <p className="text-[10px] text-muted-foreground">
                {usableReference.label}: {referenceDisplayValue}
              </p>
            </div>
          )}
        </div>
      )}

      {!usableComparison && usableReference && (
        <div className="mt-2 pt-2 border-t border-border">
          <p className="text-[10px] text-muted-foreground">
            {usableReference.label}: {referenceDisplayValue}
          </p>
        </div>
      )}
    </motion.div>
  );
};

const DisabledActivityCard = ({
  label,
  icon: Icon,
  delay = 0,
}: {
  label: string;
  icon: React.ElementType;
  delay?: number;
}) => (
  <motion.div
    initial={{ opacity: 0, y: 20 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ delay }}
    className="bg-muted/50 rounded-2xl p-4 relative overflow-hidden"
  >
    <div className="flex items-center gap-3 opacity-50">
      <div className="w-9 h-9 rounded-lg bg-muted flex items-center justify-center">
        <Icon className="w-4 h-4 text-muted-foreground" />
      </div>
      <div>
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="text-sm font-medium text-muted-foreground">데이터 없음</p>
      </div>
    </div>

    <div className="absolute inset-0 flex items-center justify-center bg-background/60">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Lock className="w-4 h-4" />
        <span className="text-xs">삼성 헬스 연동 필요</span>
      </div>
    </div>
  </motion.div>
);

interface WeightGoalCardProps {
  currentWeight: number;
  height: number;
  targetWeight: number | null;
  onSetTarget: (weight: number) => void | Promise<void>;
  averageWeightRange?: { min: number; max: number; avg: number };
}

const WeightGoalCard = ({
  currentWeight,
  height,
  targetWeight,
  onSetTarget,
  averageWeightRange,
}: WeightGoalCardProps) => {
  const [inputValue, setInputValue] = useState(targetWeight?.toString() || '');
  const [isEditing, setIsEditing] = useState(false);

  const heightM = height / 100;
  const hasValidHeight = Number.isFinite(heightM) && heightM > 0;
  const bmiMinWeight = hasValidHeight ? Math.round(BMI_NORMAL_RANGE.min * heightM * heightM * 10) / 10 : 0;
  const bmiMaxWeight = hasValidHeight ? Math.round(BMI_NORMAL_RANGE.max * heightM * heightM * 10) / 10 : 0;

  // 목표 체중의 기준 범위는 공공데이터 평균 체중이 아니라
  // 한국 성인 BMI 정상 구간(18.5~22.9)을 사용자 키에 적용해 계산한다.
  const minNormalWeight = bmiMinWeight;
  const maxNormalWeight = bmiMaxWeight;
  const hasNormalWeightRange = hasValidHeight && maxNormalWeight > minNormalWeight;

  // 공공데이터 평균 체중은 정상 범위가 아니라 참고값으로만 사용한다.
  const recommendedWeight =
    averageWeightRange && Number.isFinite(averageWeightRange.avg) && averageWeightRange.avg > 0
      ? averageWeightRange.avg
      : null;

  const handleSave = async () => {
    const weight = parseFloat(inputValue);
    if (!Number.isFinite(weight)) {
      toast.error('올바른 목표 체중을 입력해주세요.');
      return;
    }

    if (!hasValidHeight) {
      toast.error('키 정보가 없어 정상 체중 범위를 계산할 수 없습니다.');
      return;
    }

    if (weight >= minNormalWeight && weight <= maxNormalWeight) {
      await onSetTarget(weight);
      setIsEditing(false);
      toast.success('목표 체중이 설정되었습니다!');
    } else {
      toast.error(`BMI 기준 범위(${minNormalWeight}~${maxNormalWeight}kg) 내에서 설정해주세요.`);
    }
  };

  const weightDiff = targetWeight ? Math.abs(currentWeight - targetWeight) : 0;
  const isLosing = targetWeight ? currentWeight > targetWeight : false;
  const progressPercent = targetWeight && hasNormalWeightRange
    ? Math.min(
        Math.max(((currentWeight - minNormalWeight) / (maxNormalWeight - minNormalWeight)) * 100, 0),
        100
      )
    : 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2 }}
      className="bg-card rounded-2xl p-5 card-shadow"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary/20 to-info/15 flex items-center justify-center">
            <Target className="w-5 h-5 text-primary" />
          </div>
          <div>
            <p className="text-xs text-muted-foreground">목표 체중</p>
            {targetWeight ? (
              <div className="flex items-baseline gap-1">
                <span className="text-2xl font-bold text-foreground">{targetWeight}</span>
                <span className="text-sm text-muted-foreground">kg</span>
              </div>
            ) : (
              <p className="text-sm font-medium text-muted-foreground">미설정</p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {!isEditing && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setIsEditing(true)}
              disabled={!hasValidHeight}
              className="text-xs text-primary border-primary/30 hover:bg-primary/5 disabled:opacity-50"
            >
              {targetWeight ? '수정' : '설정하기'}
            </Button>
          )}
        </div>
      </div>

      {isEditing && (
        <div className="space-y-3 pt-3 border-t border-border">
          <div className="flex items-center gap-3 mt-1">
            <Input
              type="number"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="목표 체중 입력"
              className="h-11 text-base"
              step="0.1"
              min={minNormalWeight}
              max={maxNormalWeight}
            />
            <span className="text-sm text-muted-foreground whitespace-nowrap">kg</span>
          </div>

          {recommendedWeight !== null && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setInputValue(String(recommendedWeight))}
              className="text-xs text-primary"
            >
              공공데이터 평균 참고 ({recommendedWeight}kg)
            </Button>
          )}

          <p className="text-xs text-muted-foreground">
            BMI 기준 범위: <span className="font-medium text-foreground">{minNormalWeight} ~ {maxNormalWeight} kg</span>
          </p>

          <div className="p-3 bg-primary/10 rounded-xl border border-primary/20">
            <p className="text-xs text-primary flex items-start gap-2">
              <span className="text-base mt-[-2px]">💡</span>
              <span>AI 미션 생성 후에도 목표 체중은 수정할 수 있으며, 변경된 목표 체중은 이후 생성되는 AI 미션에 반영됩니다.</span>
            </p>
          </div>

          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setIsEditing(false);
                setInputValue(targetWeight?.toString() || '');
              }}
              className="flex-1 h-10"
            >
              취소
            </Button>
            <Button size="sm" onClick={handleSave} className="flex-1 h-10 gradient-primary text-primary-foreground">
              저장
            </Button>
          </div>
        </div>
      )}

      {!isEditing && targetWeight && (
        <div className="pt-3 border-t border-border space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">현재 체중 → 목표</span>
            <span className={`text-sm font-bold ${isLosing ? 'text-warning' : 'text-success'}`}>
              {isLosing ? '−' : '+'}
              {weightDiff.toFixed(1)} kg
            </span>
          </div>

          <div className="relative">
            <div className="h-3 bg-secondary rounded-full overflow-hidden">
              <motion.div
                className="h-full gradient-primary rounded-full"
                initial={{ width: 0 }}
                animate={{ width: `${progressPercent}%` }}
                transition={{ duration: 0.8, ease: 'easeOut' }}
              />
            </div>

            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.5 }}
              className="absolute top-[-3px] w-0.5 h-[18px] bg-foreground/60 rounded-full"
              style={{
                left: `${hasNormalWeightRange
                  ? Math.min(
                      Math.max(((targetWeight - minNormalWeight) / (maxNormalWeight - minNormalWeight)) * 100, 0),
                      100
                    )
                  : 0}%`,
                transform: 'translateX(-50%)',
              }}
            />

            <div className="flex justify-between mt-1.5">
              <span className="text-[10px] text-muted-foreground">{minNormalWeight}kg</span>
              <span className="text-[10px] text-muted-foreground">{maxNormalWeight}kg</span>
            </div>
          </div>
        </div>
      )}
    </motion.div>
  );
};

const DEFAULT_AVERAGE_DATA = {
  height: { min: 0, max: 0, avg: 0 },
  weight: { min: 0, max: 0, avg: 0 },
  bmi: { min: 0, max: 0, avg: 0 },
  body_fat: { min: 0, max: 0, avg: 0 },
  muscle_mass: { min: 28, max: 38, avg: 33 },
  bmr: { min: 1500, max: 1800, avg: 1650 },
};

// 한국 성인 BMI 분류 기준: 정상 18.5~22.9, 비만전단계 23.0~24.9, 비만 25.0 이상.
// 공공데이터 평균값은 참고값일 뿐 정상/위험 판정 기준으로 쓰지 않는다.
const BMI_NORMAL_RANGE: AverageRange = { min: 18.5, max: 22.9, avg: 20.7 };
const BMI_PRE_OBESITY_MAX = 24.9;

const getBmiWeightRange = (heightCm?: number | null): AverageRange => {
  const heightM = Number(heightCm || 0) / 100;

  if (!Number.isFinite(heightM) || heightM <= 0) {
    return { min: 0, max: 0, avg: 0 };
  }

  return {
    min: Math.round(BMI_NORMAL_RANGE.min * heightM * heightM * 10) / 10,
    max: Math.round(BMI_NORMAL_RANGE.max * heightM * heightM * 10) / 10,
    avg: Math.round(BMI_NORMAL_RANGE.avg * heightM * heightM * 10) / 10,
  };
};

const InBodyPage = () => {
  const navigate = useNavigate();
  const location = useLocation();

  const {
    user,
    setInBodyData,
    inBodyData,
    manualData,
    setManualData,
    hasInBodySynced,
    targetWeight,
    setTargetWeight,
  } = useAppStore();

  const { rnRequest } = useRnBridge();

  const userId = user?.id?.toString() || user?.username || 'anonymous';
  const userNickname = user?.nickname;
  const userBirthDate = user?.birthDate;
  const averageGender =
    inBodyData?.gender ||
    manualData?.gender ||
    'male';

  const averageAge =
    inBodyData?.age ||
    manualData?.age ||
    (userBirthDate ? calculateAge(userBirthDate) : null);

  const [activityData, setActivityData] = useState<{ steps?: number; calories?: number } | null>(null);
  const [isFastLoading, setIsFastLoading] = useState(true);
  const [isAverageLoading, setIsAverageLoading] = useState(true);
  const [hasFastData, setHasFastData] = useState(false);
  const [averageData, setAverageData] = useState(DEFAULT_AVERAGE_DATA);
  const [isPublicDataInfoOpen, setIsPublicDataInfoOpen] = useState(false);
  const [isActivitySyncInfoOpen, setIsActivitySyncInfoOpen] = useState(false);

  const isHealthConnectMode = !!inBodyData;
  // 게임에서 나올 때 신체 분석 화면 위에 잠깐 덮는 종료 마스크
  const [showGameExitMask, setShowGameExitMask] = useState(false);

  useEffect(() => {
    const state = location.state as { fromGameExit?: boolean } | null;

    if (state?.fromGameExit) {
      setShowGameExitMask(true);

      // 뒤로가기/재렌더 시 state 재사용 방지
      navigate(location.pathname, { replace: true, state: {} });

      const timer = window.setTimeout(() => {
        setShowGameExitMask(false);
      }, 1700);

      return () => window.clearTimeout(timer);
    }
  }, [location.pathname, location.state, navigate]);

  const applyFastData = useCallback(
    (latest: any) => {
      if (latest?.inbody) {
        const r = latest.inbody;

        if (r.source === 'manual') {
          setManualData({
            name: r.name || userNickname || '사용자',
            age: typeof r.age === 'number' ? r.age : (userBirthDate ? calculateAge(userBirthDate) : 25),
            gender: r.gender || 'male',
            height: Number(r.height || 0),
            weight: Number(r.weight || 0),
            body_fat: Number(r.body_fat || 0),
            muscle_mass: Number(r.muscle_mass || 0),
            goal: r.goal || '건강 유지',
          });
        } else if ((r.source || '').toLowerCase() === 'healthconnect') {
          setInBodyData({
            id: String(r.id ?? 'latest'),
            userId: String(r.user_id ?? 'me'),
            syncedAt: r.updated_at ? new Date(r.updated_at) : new Date(),
            name: r.name || userNickname || '사용자',
            age: typeof r.age === 'number' ? r.age : (userBirthDate ? calculateAge(userBirthDate) : 25),
            gender: r.gender || 'male',
            height: Number(r.height || 0),
            weight: Number(r.weight || 0),
            body_fat: Number(r.body_fat || 0),
            muscle_mass: Number(r.muscle_mass || 0),
            goal: r.goal || '건강 유지',
            bmi: Number(r.bmi || 0),
            bmr: Number(r.bmr || 0),
          } as any);
        } else {
          setManualData({
            name: r.name || userNickname || '사용자',
            age: typeof r.age === 'number' ? r.age : (userBirthDate ? calculateAge(userBirthDate) : 25),
            gender: r.gender || 'male',
            height: Number(r.height || 0),
            weight: Number(r.weight || 0),
            body_fat: Number(r.body_fat || 0),
            muscle_mass: Number(r.muscle_mass || 0),
            goal: r.goal || '건강 유지',
          });
        }

        if (typeof r.target_weight === 'number' && r.target_weight > 0) {
          setTargetWeight(Number(r.target_weight));
        }
      }

      if (latest?.activity) {
        const act = latest.activity;
        setActivityData({
          steps: typeof act.steps === 'number' ? act.steps : Number(act.steps || 0),
          calories: typeof act.calories === 'number' ? act.calories : Number(act.calories || 0),
        });
      } else {
        setActivityData(null);
      }

      setHasFastData(Boolean(latest?.activity));
    },
    [setInBodyData, setManualData, setTargetWeight, userNickname, userBirthDate]
  );

  const applyAverageData = useCallback(
    (avgResponse: any) => {
      const avg = avgResponse?.average;
      if (!avg) return;

      // 공공데이터 평균값은 정상범위가 아니라 비교용 참고값이다.
      // min/max는 그래프 표시용 참고구간으로만 사용하고, 의학 판정에는 쓰지 않는다.
      const range = (x: number, pct = 0.1) => ({
        min: +(x * (1 - pct)).toFixed(1),
        max: +(x * (1 + pct)).toFixed(1),
        avg: +x.toFixed(1),
      });

      const avgHeight = Number(avg.avg_height);
      const avgWeight = Number(avg.avg_weight);
      const avgBodyFat = Number(avg.avg_body_fat);
      const avgBmi = Number(avg.avg_bmi);

      const nextAverageData = {
        height: Number.isFinite(avgHeight) ? range(avgHeight, 0.03) : DEFAULT_AVERAGE_DATA.height,
        weight: Number.isFinite(avgWeight) ? range(avgWeight, 0.1) : DEFAULT_AVERAGE_DATA.weight,
        body_fat: Number.isFinite(avgBodyFat) ? range(avgBodyFat, 0.15) : DEFAULT_AVERAGE_DATA.body_fat,
        bmi: Number.isFinite(avgBmi) ? range(avgBmi, 0.1) : DEFAULT_AVERAGE_DATA.bmi,
      };

      setAverageData((prev) => ({
        ...prev,
        ...nextAverageData,
      }));

      writeAverageCache(
        {
          userId,
          gender: averageGender,
          age: averageAge,
        },
        nextAverageData
      );
    },
    [userId, averageGender, averageAge]
  );

  const saveTargetWeight = useCallback(
    async (weight: number) => {
      const token = localStorage.getItem('access_token');

      if (!token) {
        toast.error('로그인이 필요합니다.');
        return;
      }

      try {
        await rnRequest('HEALTHCARE_TARGET_WEIGHT_SAVE_REQUEST', {
          token,
          targetWeight: weight,
        });

        setTargetWeight(weight);
        toast.success('목표 체중이 저장되었습니다.');
      } catch (e: any) {
        toast.error(e?.message ? String(e.message) : '목표 체중 저장에 실패했습니다.');
      }
    },
    [setTargetWeight, rnRequest]
  );

  useEffect(() => {
    const token = localStorage.getItem('access_token');
    if (!token) {
      setIsFastLoading(false);
      setIsAverageLoading(false);
      return;
    }

    let cancelled = false;

    const fetchFast = async () => {
      try {
        const fast = await rnRequest('HEALTHCARE_LATEST_FAST_REQUEST', { token });
        if (!cancelled) applyFastData(fast);
      } catch {
        // ignore
      } finally {
        if (!cancelled) setIsFastLoading(false);
      }
    };

    const fetchAverage = async () => {
      const cached = readAverageCache({
        userId,
        gender: averageGender,
        age: averageAge,
      });

      if (cached?.data && !cancelled) {
        setAverageData((prev) => ({
          ...prev,
          ...cached.data,
        }));
        setIsAverageLoading(false);
      }

      if (cached && !isAverageCacheExpired(cached.savedAt)) {
        return;
      }

      try {
        if (!cached && !cancelled) {
          setIsAverageLoading(true);
        }

        const avg = await rnRequest('HEALTHCARE_AVERAGE_REQUEST', { token });
        console.log('[HEALTHCARE_AVERAGE_RESPONSE]', avg);

        if (!cancelled) {
          applyAverageData(avg);
          setIsAverageLoading(false);
        }
      } catch {
        if (!cancelled) {
          setIsAverageLoading(false);
        }
      }
    };

    fetchFast();
    fetchAverage();

    return () => {
      cancelled = true;
    };
  }, [applyFastData, applyAverageData, rnRequest, userId, averageGender, averageAge]);

  const userData = inBodyData
    ? inBodyData
    : manualData
      ? {
          height: manualData.height ?? 0,
          weight: manualData.weight ?? 0,
          bmi:
            manualData.height && manualData.weight
              ? manualData.weight / ((manualData.height / 100) ** 2)
              : 0,
          body_fat: manualData.body_fat ?? 0,
          muscle_mass: manualData.muscle_mass ?? 0,
          bmr:
            manualData.gender === 'male'
              ? 88.362 +
                13.397 * (manualData.weight ?? 0) +
                4.799 * (manualData.height ?? 0) -
                5.677 * (manualData.age ?? 0)
              : 447.593 +
                9.247 * (manualData.weight ?? 0) +
                3.098 * (manualData.height ?? 0) -
                4.33 * (manualData.age ?? 0),
        }
      : null;

  const normalWeightRange = userData
    ? getBmiWeightRange(userData.height)
    : DEFAULT_AVERAGE_DATA.weight;

  const getBmiStatus = (value: number): 'good' | 'warning' | 'bad' => {
    if (value >= BMI_NORMAL_RANGE.min && value <= BMI_NORMAL_RANGE.max) return 'good';
    if (value > BMI_PRE_OBESITY_MAX || value < 16) return 'bad';
    return 'warning';
  };

  const publicAverageHeightReady = Number.isFinite(averageData.height.avg) && averageData.height.avg > 0;
  const publicAverageWeightReady = Number.isFinite(averageData.weight.avg) && averageData.weight.avg > 0;
  const publicAverageBmiReady = Number.isFinite(averageData.bmi.avg) && averageData.bmi.avg > 0;
  const publicAverageBodyFatReady = Number.isFinite(averageData.body_fat.avg) && averageData.body_fat.avg > 0;

  if (!isFastLoading && !userData) {
    return (
      <AppLayout>
        <div className="flex flex-col h-full">
          <div className="gradient-primary px-6 pt-safe-top pb-6">
            <h1 className="text-xl font-bold text-primary-foreground">신체 분석 데이터</h1>
          </div>

          <div className="flex-1 flex items-center justify-center p-6">
            <div className="text-center">
              <div className="w-20 h-20 mx-auto rounded-full bg-locked/20 flex items-center justify-center mb-4">
                <Scale className="w-10 h-10 text-locked" />
              </div>

              <h2 className="text-xl font-bold text-foreground">데이터가 없습니다</h2>
              <p className="text-muted-foreground mt-2">
                신체 정보를 입력하면
                <br />
                상세 분석을 확인할 수 있어요
              </p>

              <button
                onClick={() => navigate('/onboarding')}
                className="mt-6 px-8 py-3 rounded-xl gradient-primary text-primary-foreground font-semibold"
              >
                정보 입력하기
              </button>
            </div>
          </div>
        </div>
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      <div className="gradient-primary px-6 pt-safe-top pb-6">
        <div className="flex items-center justify-between pt-3">
          <h1 className="text-xl font-bold text-primary-foreground">신체 분석 데이터</h1>
          <button
            onClick={() => navigate('/history')}
            className="w-10 h-10 rounded-xl bg-primary-foreground/10 flex items-center justify-center"
          >
            <History className="w-5 h-5 text-primary-foreground" />
          </button>
        </div>

        {inBodyData && (
          <p className="text-primary-foreground/70 text-sm mt-3">
            마지막 동기화:{' '}
            {new Date(inBodyData.syncedAt).toLocaleString('ko-KR', {
              timeZone: 'Asia/Seoul',
            })}
          </p>
        )}
      </div>

      <div className="px-6 py-4 space-y-4">
        <div>
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <Activity className="w-4 h-4 text-primary" />
              활동
            </h2>

            {isHealthConnectMode && (
              <button
                type="button"
                onClick={() => setIsActivitySyncInfoOpen(true)}
                aria-label="활동 동기화 안내 보기"
                className="w-7 h-7 shrink-0 rounded-full bg-muted/80 border border-border flex items-center justify-center text-muted-foreground active:scale-95 transition-transform"
              >
                <HelpCircle className="w-4 h-4" />
              </button>
            )}
          </div>

          {isFastLoading ? (
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-card rounded-2xl p-4 card-shadow animate-pulse h-24" />
              <div className="bg-card rounded-2xl p-4 card-shadow animate-pulse h-24" />
            </div>
          ) : hasFastData ? (
            <div className="grid grid-cols-2 gap-3">
              <MetricCard
                label="걸음 수"
                value={activityData?.steps?.toLocaleString() || '0'}
                unit="걸음"
                icon={Footprints}
                delay={0.1}
                showStatus={false}
              />
              <MetricCard
                label="활동 칼로리"
                value={activityData?.calories?.toLocaleString() || '0'}
                unit="kcal"
                icon={Flame}
                delay={0.15}
                showStatus={false}
              />
            </div>
          ) : hasInBodySynced ? (
            <div className="grid grid-cols-2 gap-3">
              <MetricCard label="걸음 수" value="--" unit="걸음" icon={Footprints} delay={0.1} showStatus={false} />
              <MetricCard label="활동 칼로리" value="--" unit="kcal" icon={Flame} delay={0.15} showStatus={false} />
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <DisabledActivityCard label="걸음 수" icon={Footprints} delay={0.1} />
              <DisabledActivityCard label="활동 칼로리" icon={Flame} delay={0.15} />
            </div>
          )}
        </div>

        {userData && (
          <div>
            <div className="flex items-center justify-between gap-3 mb-3">
              <h2 className="text-sm font-semibold text-foreground flex items-center gap-2 shrink-0">
                <Heart className="w-4 h-4 text-primary" />
                신체 지표
              </h2>

              <div className="flex items-center gap-3 min-w-0">
                {isAverageLoading ? (
                  <motion.div
                    initial={{ opacity: 0, x: 10 }}
                    animate={{ opacity: 1, x: 0 }}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-warning/15 border border-warning/30 whitespace-nowrap"
                  >
                    <Loader2 className="w-3 h-3 text-warning animate-spin shrink-0" />
                    <span className="text-[11px] font-medium text-warning">공공데이터 불러오는 중...</span>
                  </motion.div>
                ) : (
                  <motion.div
                    initial={{ opacity: 0, scale: 0.8 }}
                    animate={{ opacity: 1, scale: 1 }}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-success/15 border border-success/30 whitespace-nowrap"
                  >
                    <Check className="w-3 h-3 text-success shrink-0" />
                    <span className="text-[11px] font-medium text-success">공공데이터 불러오기 완료</span>
                  </motion.div>
                )}

                <button
                  type="button"
                  onClick={() => setIsPublicDataInfoOpen(true)}
                  aria-label="공공데이터 설명 보기"
                  className="w-7 h-7 shrink-0 rounded-full bg-muted/80 border border-border flex items-center justify-center text-muted-foreground active:scale-95 transition-transform"
                >
                  <HelpCircle className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <MetricCard
                  label="키"
                  value={userData.height.toFixed(1)}
                  unit="cm"
                  icon={Ruler}
                  delay={0.3}
                  showStatus={false}
                  reference={
                    isAverageLoading || publicAverageHeightReady
                      ? {
                          label: '공공데이터 평균',
                          value: publicAverageHeightReady ? averageData.height.avg : null,
                          unit: 'cm',
                          isLoading: isAverageLoading,
                        }
                      : undefined
                  }
                />
                <MetricCard
                  label="몸무게"
                  value={userData.weight.toFixed(1)}
                  unit="kg"
                  status={getBmiStatus(userData.bmi)}
                  comparison={{
                    avgMin: normalWeightRange.min,
                    avgMax: normalWeightRange.max,
                    userValue: userData.weight,
                  }}
                  comparisonLabel="BMI 기준 범위"
                  reference={
                    isAverageLoading || publicAverageWeightReady
                      ? {
                          label: '공공데이터 평균',
                          value: publicAverageWeightReady ? averageData.weight.avg : null,
                          unit: 'kg',
                          isLoading: isAverageLoading,
                        }
                      : undefined
                  }
                  icon={Scale}
                  delay={0.35}
                />
              </div>

              <WeightGoalCard
                currentWeight={userData.weight}
                height={userData.height}
                targetWeight={targetWeight}
                onSetTarget={saveTargetWeight}
                averageWeightRange={publicAverageWeightReady ? averageData.weight : undefined}
              />

              <div className="grid grid-cols-2 gap-3">
                <MetricCard
                  label="BMI"
                  value={userData.bmi.toFixed(1)}
                  unit=""
                  status={getBmiStatus(userData.bmi)}
                  comparison={{
                    avgMin: BMI_NORMAL_RANGE.min,
                    avgMax: BMI_NORMAL_RANGE.max,
                    userValue: userData.bmi,
                  }}
                  comparisonLabel="BMI 정상 범위"
                  reference={
                    isAverageLoading || publicAverageBmiReady
                      ? {
                          label: '공공데이터 기반 평균',
                          value: publicAverageBmiReady ? averageData.bmi.avg : null,
                          isLoading: isAverageLoading,
                        }
                      : undefined
                  }
                  icon={Heart}
                  delay={0.4}
                />
                <MetricCard
                  label="체지방률(추정)"
                  value={userData.body_fat.toFixed(1)}
                  unit="%"
                  icon={Droplets}
                  delay={0.45}
                  showStatus={false}
                  reference={
                    isAverageLoading || publicAverageBodyFatReady
                      ? {
                          label: '공공데이터 기반 추정 평균',
                          value: publicAverageBodyFatReady ? averageData.body_fat.avg : null,
                          unit: '%',
                          isLoading: isAverageLoading,
                        }
                      : undefined
                  }
                />
              </div>
            </div>
          </div>
        )}
      </div>


      <AnimatePresence>
        {isHealthConnectMode && isActivitySyncInfoOpen && (
          <motion.div
            className="fixed inset-0 z-[90] flex items-center justify-center bg-black/45 px-6"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setIsActivitySyncInfoOpen(false)}
          >
            <motion.div
              role="dialog"
              aria-modal="true"
              aria-labelledby="activity-sync-info-title"
              className="w-full max-w-sm rounded-3xl bg-card p-5 shadow-2xl border border-border"
              initial={{ opacity: 0, y: 18, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 18, scale: 0.96 }}
              transition={{ duration: 0.18 }}
              onClick={(event) => event.stopPropagation()}
            >
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-2xl bg-primary/10 flex items-center justify-center shrink-0">
                  <HelpCircle className="w-5 h-5 text-primary" />
                </div>

                <div>
                  <h3 id="activity-sync-info-title" className="text-base font-bold text-foreground">
                    활동 동기화 안내
                  </h3>
                  <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
                    어떻게 반영되는지 알려드릴게요.
                  </p>
                </div>
              </div>

              <div className="mt-4 space-y-3 text-sm text-foreground leading-relaxed">
                <p>
                  이 영역의 걸음 수와 활동 칼로리는 Samsung Health / Health Connect에 저장된 데이터를
                  기반으로 표시됩니다.
                </p>
                <p>
                  초기 연동 후에는 앱에서 저장된 최신 동기화 데이터를 불러오며, 사용 중 값이 바로
                  바뀌지 않았다면 Health Connect 쪽 반영에 시간이 조금 걸릴 수 있습니다.
                </p>
                <p>
                  최신 값이 보이지 않으면 <span className="font-semibold text-primary">프로필 → Samsung Health 동기화 갱신</span>에서
                  수동 동기화를 진행해 주세요.
                </p>
                <div className="rounded-2xl bg-muted/60 px-3 py-3 text-xs text-muted-foreground space-y-2">
                  <p className="font-semibold text-foreground">연동이 잘 안될 때 체크해보세요</p>
                  <ul className="list-disc pl-4 space-y-1">
                    <li>Samsung Health와 Health Connect가 서로 연결되어 있는지 확인</li>
                    <li>걸음 수, 키, 몸무게 권한이 모두 허용되어 있는지 확인</li>
                    <li>네트워크 연결을 확인한 뒤 앱을 다시 열고 재시도</li>
                    <li>값이 계속 안 바뀌면 Samsung Health에 최신 키·몸무게가 저장되어 있는지 확인한 뒤 다시 동기화</li>
                  </ul>
                </div>
              </div>

              <Button
                type="button"
                onClick={() => setIsActivitySyncInfoOpen(false)}
                className="mt-5 w-full rounded-2xl"
              >
                확인했어요
              </Button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {isPublicDataInfoOpen && (
          <motion.div
            className="fixed inset-0 z-[90] flex items-center justify-center bg-black/45 px-6"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setIsPublicDataInfoOpen(false)}
          >
            <motion.div
              role="dialog"
              aria-modal="true"
              aria-labelledby="public-data-info-title"
              className="w-full max-w-sm rounded-3xl bg-card p-5 shadow-2xl border border-border"
              initial={{ opacity: 0, y: 18, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 18, scale: 0.96 }}
              transition={{ duration: 0.18 }}
              onClick={(event) => event.stopPropagation()}
            >
              <div className="flex items-start gap-3">
                <div className="w-10 h-10 rounded-2xl bg-primary/10 flex items-center justify-center shrink-0">
                  <HelpCircle className="w-5 h-5 text-primary" />
                </div>

                <div>
                  <h3 id="public-data-info-title" className="text-base font-bold text-foreground">
                    공공데이터 기준 안내
                  </h3>
                  <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
                    신체 지표의 평균 비교값이 어떤 기준으로 표시되는지 알려드릴게요.
                  </p>
                </div>
              </div>

              <div className="mt-4 space-y-3 text-sm text-foreground leading-relaxed">
                <p>
                  이 화면의 평균 비교값은 국가통계포털 KOSIS에서 제공되는 국민건강보험공단
                  건강검진통계 공공데이터를 참고해 표시됩니다.
                </p>
                <p>
                  현재 앱에서는 KOSIS에서 제공되는 최근 공개 기준 데이터를 바탕으로 사용자의 나이와 성별에 맞는
                  연령 구간의 평균값을 비교 기준으로 사용합니다.
                </p>
                <p>
                  공공데이터 원본에서 직접 제공되는 값은 평균 키와 평균 체중이며, BMI와
                  체지방률은 이 평균 키·체중 값을 바탕으로 앱에서 계산한 참고용 추정값입니다.
                </p>
                <p className="text-xs text-muted-foreground">
                  이 정보는 평균 비교와 AI 미션 생성을 돕기 위한 참고 자료이며, 의학적 진단이나
                  치료 판단을 대신하지 않습니다.
                </p>
              </div>

              <Button
                type="button"
                onClick={() => setIsPublicDataInfoOpen(false)}
                className="mt-5 w-full rounded-2xl"
              >
                확인했어요
              </Button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showGameExitMask && (
          <motion.div
            className="fixed inset-0 z-[100] flex items-center justify-center pointer-events-none"
            initial={{ opacity: 1 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <motion.div
              className="absolute inset-0 bg-gradient-to-br from-slate-900 via-violet-900 to-purple-900"
              initial={{ scale: 1, borderRadius: '0%' }}
              animate={{ scale: 0, borderRadius: '100%' }}
              transition={{ duration: 0.55, ease: 'easeOut', delay: 0.95 }}
            />

            <motion.div
              className="absolute inset-0 bg-black/35"
              initial={{ opacity: 1 }}
              animate={{ opacity: 0 }}
              transition={{ duration: 0.35, delay: 0.9 }}
            />

            <div className="relative z-10 flex flex-col items-center gap-5">
              <motion.div
                className="relative"
                initial={{ scale: 1, rotate: 0, opacity: 1 }}
                animate={{
                  scale: [1, 1, 1.1, 0],
                  rotate: [0, 0, 220, 420],
                  opacity: [1, 1, 1, 0],
                }}
                transition={{
                  duration: 1.45,
                  times: [0, 0.7, 0.88, 1],
                  ease: 'easeInOut',
                }}
              >
                <motion.div
                  className="absolute inset-0 bg-yellow-400/30 rounded-full blur-2xl"
                  initial={{ scale: 1.3, opacity: 0.8 }}
                  animate={{ scale: 0, opacity: 0 }}
                  transition={{ duration: 0.45, delay: 0.9 }}
                />

                <div className="relative w-28 h-28 bg-gradient-to-br from-violet-600 to-purple-700 rounded-2xl flex items-center justify-center border-4 border-white/30 shadow-2xl">
                  <Gamepad2 className="w-14 h-14 text-white drop-shadow-[0_2px_4px_rgba(0,0,0,0.5)]" />
                  <div className="absolute -top-1 -left-1 w-3 h-3 bg-white rounded-sm" />
                  <div className="absolute -top-1 -right-1 w-3 h-3 bg-white rounded-sm" />
                  <div className="absolute -bottom-1 -left-1 w-3 h-3 bg-white rounded-sm" />
                  <div className="absolute -bottom-1 -right-1 w-3 h-3 bg-white rounded-sm" />
                </div>

                <motion.div
                  className="absolute -top-2 -right-2"
                  initial={{ rotate: 0, opacity: 1 }}
                  animate={{ rotate: -540, scale: 0, opacity: 0 }}
                  transition={{ duration: 0.45, delay: 0.85 }}
                >
                  <Sparkles className="w-6 h-6 text-yellow-400" />
                </motion.div>

                <motion.div
                  className="absolute -bottom-2 -left-2"
                  initial={{ scale: 1, opacity: 1 }}
                  animate={{ scale: 0, opacity: 0 }}
                  transition={{ duration: 0.35, delay: 0.9 }}
                >
                  <Zap className="w-6 h-6 text-white" />
                </motion.div>
              </motion.div>

              <motion.div
                className="text-center"
                initial={{ opacity: 1, y: 0 }}
                animate={{ opacity: 0, y: -16 }}
                transition={{ delay: 0.9, duration: 0.35 }}
              >
                <h2
                  className="text-3xl font-black text-white mb-2 drop-shadow-[0_4px_8px_rgba(0,0,0,0.8)]"
                  style={{
                    textShadow: '0 2px 10px rgba(0,0,0,0.9), 0 0 30px rgba(139,92,246,0.5)',
                  }}
                >
                  게임 나가는 중!
                </h2>
                <p className="text-white text-sm font-medium drop-shadow-[0_2px_4px_rgba(0,0,0,0.8)]">
                  다음에 또 만나요
                </p>
              </motion.div>

              <motion.div
                className="flex gap-2"
                initial={{ opacity: 1 }}
                animate={{ opacity: 0 }}
                transition={{ delay: 0.85, duration: 0.25 }}
              >
                {[0, 1, 2].map((i) => (
                  <motion.div
                    key={i}
                    className="w-3 h-3 bg-white rounded-full"
                    animate={{ y: [-5, 5, -5] }}
                    transition={{ duration: 0.35, repeat: 2, delay: i * 0.06 }}
                  />
                ))}
              </motion.div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </AppLayout>
  );
};

export default InBodyPage;