/**
 * 👤 프로필 세부 정보 페이지 (백엔드 통합)
 *
 * - 프로필 이름 / 생년월일 / 이미지: FastAPI DB 저장
 * - 프로필 이미지는 5MB 이하 data URL만 허용
 * - RN WebView 환경에서는 실제 사진 권한 요청 후 이미지 선택
 * - 미션 성공 내역 / C타입 기록 / 결제 내역 / 활동 요약: 백엔드 조회
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import type React from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import {
  ChevronLeft,
  Camera,
  Pencil,
  CheckCircle2,
  NotebookPen,
  Footprints,
  Receipt,
  CalendarDays,
  Trophy,
  ChevronRight,
  Activity,
  Moon,
  X,
  PenLine,
  Flame,
  Droplets,
  Trash2,
  RefreshCw,
} from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogClose,
} from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Button } from '@/components/ui/button';
import { useAppStore } from '@/stores/appStore';
import { useRnBridge } from '@/hooks/useRnBridge';
import { healthcareApi, profileApi } from '@/services/api';
import { toast } from 'sonner';
import type {
  MissionType,
  ProfileDetailsResponse,
  ProfileMissionHistoryItem,
  ProfilePaymentItem,
  ProfileRoutineLogItem,
} from '@/types';

const MAX_PROFILE_IMAGE_BYTES = 5 * 1024 * 1024;

const DETAIL_DIALOG_CONTENT_CLASS =
  'w-[calc(100vw-32px)] max-w-[380px] sm:max-w-[420px] p-0 gap-0 max-h-[72vh] overflow-hidden rounded-2xl box-border [&>button]:hidden';

const MIN_PROFILE_AGE = 14;
const AVERAGE_CACHE_KEY_PREFIX = 'healthcare_average_cache_v4';

const calculateAge = (birthDate: string): number | null => {
  if (!birthDate) return null;

  const birth = new Date(birthDate);
  if (Number.isNaN(birth.getTime())) return null;

  const today = new Date();
  let age = today.getFullYear() - birth.getFullYear();
  const monthDiff = today.getMonth() - birth.getMonth();

  if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birth.getDate())) {
    age -= 1;
  }

  return age;
};

const getBirthDateError = (value: string): string | null => {
  if (!value) return null;

  const birth = new Date(value);
  if (Number.isNaN(birth.getTime())) {
    return '생년월일을 올바르게 입력해주세요.';
  }

  const today = new Date();
  const todayDateOnly = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const birthDateOnly = new Date(birth.getFullYear(), birth.getMonth(), birth.getDate());

  if (birthDateOnly.getTime() > todayDateOnly.getTime()) {
    return '미래 날짜는 생년월일로 설정할 수 없습니다.';
  }

  const age = calculateAge(value);
  if (age === null) {
    return '생년월일을 올바르게 입력해주세요.';
  }

  if (age < MIN_PROFILE_AGE) {
    return '만 14세 이상만 설정할 수 있습니다.';
  }

  return null;
};

const clearPublicAverageCaches = () => {
  try {
    Object.keys(localStorage).forEach((key) => {
      if (key.startsWith(`${AVERAGE_CACHE_KEY_PREFIX}:`)) {
        localStorage.removeItem(key);
      }
    });
  } catch {
    // localStorage 접근 실패는 저장 흐름을 막지 않는다.
  }
};

const getPublicAverageCacheKey = ({
  userId,
  gender,
  age,
}: {
  userId?: string | number | null;
  gender?: string | null;
  age?: number | null;
}) => {
  const accountKey = userId?.toString() || 'anonymous';
  const genderKey = (gender || 'unknown').toLowerCase();
  const ageKey = age && Number.isFinite(age) ? String(Math.floor(age)) : 'unknown';

  return `${AVERAGE_CACHE_KEY_PREFIX}:${accountKey}:${genderKey}:${ageKey}`;
};

const buildAverageCacheData = (avg: any) => {
  if (!avg) return null;

  const range = (x: number, pct = 0.1) => ({
    min: +(x * (1 - pct)).toFixed(1),
    max: +(x * (1 + pct)).toFixed(1),
    avg: +x.toFixed(1),
  });

  const avgHeight = Number(avg.avg_height);
  const avgWeight = Number(avg.avg_weight);
  const avgBodyFat = Number(avg.avg_body_fat);
  const avgBmi = Number(avg.avg_bmi);

  return {
    height: Number.isFinite(avgHeight) && avgHeight > 0 ? range(avgHeight, 0.03) : { min: 0, max: 0, avg: 0 },
    weight: Number.isFinite(avgWeight) && avgWeight > 0 ? range(avgWeight, 0.1) : { min: 0, max: 0, avg: 0 },
    body_fat: Number.isFinite(avgBodyFat) && avgBodyFat > 0 ? range(avgBodyFat, 0.15) : { min: 0, max: 0, avg: 0 },
    bmi: Number.isFinite(avgBmi) && avgBmi > 0 ? range(avgBmi, 0.1) : { min: 0, max: 0, avg: 0 },
  };
};

const writePublicAverageCache = ({
  userId,
  average,
}: {
  userId?: string | number | null;
  average: any;
}) => {
  try {
    const avg = average?.average;
    const data = buildAverageCacheData(avg);
    if (!avg || !data) return;

    const key = getPublicAverageCacheKey({
      userId,
      gender: avg.gender,
      age: Number(avg.requested_test_age),
    });

    localStorage.setItem(
      key,
      JSON.stringify({
        savedAt: Date.now(),
        data,
      })
    );
  } catch {
    // 캐시 저장 실패는 무시한다. 신체 분석 화면에서 다시 호출하면 된다.
  }
};

type MissionTypeKey = MissionType;

type MissionMeta = {
  label: string;
  category: '활동' | '루틴' | '기록';
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  bg: string;
  badge: string;
};

const A_TYPE_THEME = {
  bg: 'bg-blue-100',
  color: 'text-blue-600',
  badge: 'bg-blue-100 text-blue-700',
};

const B_TYPE_THEME = {
  bg: 'bg-green-100',
  color: 'text-green-600',
  badge: 'bg-green-100 text-green-700',
};

const C_TYPE_THEME = {
  bg: 'bg-amber-100',
  color: 'text-amber-600',
  badge: 'bg-muted text-muted-foreground',
};

const MISSION_META: Record<MissionTypeKey, MissionMeta> = {
  A1_STEP_TARGET: {
    label: '걸음 목표 달성',
    category: '활동',
    icon: Footprints,
    ...A_TYPE_THEME,
  },
  A2_ACTIVE_KCAL_TARGET: {
    label: '활동 칼로리 달성',
    category: '활동',
    icon: Flame,
    ...A_TYPE_THEME,
  },
  B1_TIMER_STRETCH: {
    label: '스트레칭 타이머',
    category: '루틴',
    icon: Activity,
    ...B_TYPE_THEME,
  },
  B2_SLEEP_PREP: {
    label: '수면 준비 루틴',
    category: '루틴',
    icon: Moon,
    ...B_TYPE_THEME,
  },
  B3_ROUTINE_CHECK: {
    label: '루틴 체크',
    category: '루틴',
    icon: Droplets,
    ...B_TYPE_THEME,
  },
  C1_HEALTH_CHECKIN: {
    label: '건강 기록',
    category: '기록',
    icon: PenLine,
    ...C_TYPE_THEME,
  },
};

const DEFAULT_MISSION_META: MissionMeta = {
  label: 'AI 미션',
  category: '기록',
  icon: CheckCircle2,
  color: 'text-slate-600',
  bg: 'bg-slate-100',
  badge: 'bg-slate-100 text-slate-700',
};

const getDataUrlBytes = (dataUrl: string): number => {
  const base64 = dataUrl.split(',')[1] || '';
  const padding = base64.endsWith('==') ? 2 : base64.endsWith('=') ? 1 : 0;
  return Math.max(0, Math.floor((base64.length * 3) / 4) - padding);
};

const validateProfileImageDataUrl = (dataUrl: string) => {
  if (!dataUrl.startsWith('data:image/')) {
    throw new Error('이미지 파일만 등록할 수 있어요.');
  }

  if (getDataUrlBytes(dataUrl) > MAX_PROFILE_IMAGE_BYTES) {
    throw new Error('5MB 이하 이미지만 등록해주세요.');
  }
};

const formatDate = (value?: string | null) => {
  if (!value) return '-';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value.slice(0, 10);
  return d.toLocaleDateString('ko-KR');
};

const SectionCard = ({
  title,
  icon: Icon,
  children,
  action,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  children: React.ReactNode;
  action?: React.ReactNode;
}) => (
  <section className="bg-card rounded-2xl border border-border/60 shadow-sm overflow-hidden">
    <header className="flex items-center justify-between px-5 py-4 border-b border-border/50">
      <div className="flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center">
          <Icon className="w-4 h-4 text-foreground/70" />
        </div>
        <h3 className="text-[15px] font-semibold text-foreground tracking-tight">{title}</h3>
      </div>
      {action}
    </header>
    <div className="px-5 py-4">{children}</div>
  </section>
);

const Stat = ({ label, value, sub }: { label: string; value: string; sub?: string }) => (
  <div className="flex-1 min-w-0">
    <p className="text-xs text-muted-foreground">{label}</p>
    <p className="mt-1 text-xl font-bold text-foreground tabular-nums truncate">{value}</p>
    {sub && <p className="text-[11px] text-muted-foreground mt-0.5">{sub}</p>}
  </div>
);

const ViewAllButton = ({ onClick, disabled }: { onClick: () => void; disabled?: boolean }) => (
  <button
    onClick={onClick}
    disabled={disabled}
    className="text-xs text-muted-foreground hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-0.5"
  >
    전체보기 <ChevronRight className="w-3.5 h-3.5" />
  </button>
);

const EmptyList = ({ text }: { text: string }) => (
  <div className="py-6 text-center text-xs text-muted-foreground">{text}</div>
);

const MissionRow = ({ m }: { m: ProfileMissionHistoryItem }) => {
  const meta =
    (m.mission_type && MISSION_META[m.mission_type as MissionTypeKey]) ||
    DEFAULT_MISSION_META;

  const Icon = meta.icon;

  return (
    <li className="rounded-xl border border-border/60 bg-card px-3 py-3 shadow-sm overflow-hidden">
      <div className="flex items-start gap-3 min-w-0">
        <div
          className={`w-9 h-9 rounded-lg ${meta.bg} ${meta.color} flex items-center justify-center shrink-0 mt-0.5`}
        >
          <Icon className="w-4 h-4" />
        </div>

        <div className="flex-1 min-w-0 overflow-hidden">
          <div className="mb-1">
            <span className="inline-flex text-[10px] font-semibold text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
              {meta.category}
            </span>
          </div>

          <p className="text-sm font-semibold text-foreground leading-snug whitespace-normal break-words">
            {m.title || meta.label}
          </p>

          <p className="text-[11px] text-muted-foreground mt-1.5 leading-relaxed break-words">
            {formatDate(m.date)}
            {m.detail ? ` · ${m.detail}` : ''}
          </p>
        </div>
      </div>
    </li>
  );
};

const RoutineRow = ({ r }: { r: ProfileRoutineLogItem }) => (
  <li className="rounded-xl border border-border/50 bg-background/60 p-3">
    <div className="flex items-center justify-between gap-3">
      <p className="text-sm font-semibold text-foreground truncate">{r.title || '건강 기록'}</p>
      <span className="text-[11px] text-muted-foreground shrink-0">{formatDate(r.date)}</span>
    </div>
    <p className="mt-1.5 text-xs text-muted-foreground leading-relaxed">{r.note || '기록형 미션을 완료했습니다.'}</p>
  </li>
);

const PaymentRow = ({ p }: { p: ProfilePaymentItem }) => (
  <li className="py-3 px-1 flex items-center justify-between gap-3">
    <div className="min-w-0">
      <p className="text-sm font-medium text-foreground truncate">{p.item}</p>
      <p className="text-[11px] text-muted-foreground mt-0.5">
        {formatDate(p.date)} · {p.status}
      </p>
    </div>
    <p className="text-sm font-semibold text-foreground tabular-nums shrink-0">
      {Number(p.amount || 0).toLocaleString()}원
    </p>
  </li>
);

const ProfileDetailsPage = () => {
  const navigate = useNavigate();
  const { user, updateUser, setPermissions } = useAppStore();
  const { rnRequest, isRnWebViewAvailable } = useRnBridge();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [details, setDetails] = useState<ProfileDetailsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isPickingImage, setIsPickingImage] = useState(false);

  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [name, setName] = useState(user?.nickname || '사용자');
  const [birthDate, setBirthDate] = useState<string>((user as any)?.birthDate || '');
  const [birthDateError, setBirthDateError] = useState<string | null>(null);
  const [avatarError, setAvatarError] = useState<string | null>(null);

  const [showMissionsAll, setShowMissionsAll] = useState(false);
  const [showRoutinesAll, setShowRoutinesAll] = useState(false);
  const [showPaymentsAll, setShowPaymentsAll] = useState(false);

  const loadDetails = async () => {
    setIsLoading(true);
    try {
      const data = await profileApi.getDetails();
      setDetails(data);
      setName(data.profile.name || '사용자');
      setBirthDate(data.profile.birth_date || '');
      setBirthDateError(null);
      setAvatarUrl(data.profile.profile_image_data_url || null);
      setPermissions({ image: !!data.profile.image_permission_granted });
    } catch (e: any) {
      toast.error(e?.message ? String(e.message) : '프로필 세부 정보를 불러오지 못했습니다.');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadDetails();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const createdAt = details?.profile.created_at || (typeof user?.createdAt === 'string' ? user.createdAt : null);

  const getLocalDateKey = (date: Date) => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');

    return `${year}-${month}-${day}`;
  };

  const [todayKey, setTodayKey] = useState(() => getLocalDateKey(new Date()));

  useEffect(() => {
    const updateTodayKey = () => {
      setTodayKey(getLocalDateKey(new Date()));
    };

    updateTodayKey();

    const timer = window.setInterval(updateTodayKey, 60 * 1000);

    return () => {
      window.clearInterval(timer);
    };
  }, []);

  const daysWithApp = useMemo(() => {
    if (!createdAt) return 1;

    const start = new Date(createdAt);
    if (Number.isNaN(start.getTime())) return 1;

    const startDateOnly = new Date(
      start.getFullYear(),
      start.getMonth(),
      start.getDate(),
    );

    const today = new Date();
    const todayDateOnly = new Date(
      today.getFullYear(),
      today.getMonth(),
      today.getDate(),
    );

    const diffDays = Math.floor(
      (todayDateOnly.getTime() - startDateOnly.getTime()) / (1000 * 60 * 60 * 24),
    );

    return Math.max(1, diffDays + 1);
  }, [createdAt, todayKey]);

  const installDateLabel = createdAt ? formatDate(createdAt) : '-';

  const missionHistory = details?.mission_history ?? [];
  const routineLogs = details?.routine_logs ?? [];
  const payments = details?.payments ?? [];

  const missionsPreview = missionHistory.slice(0, 3);
  const routinesPreview = routineLogs.slice(0, 3);
  const paymentsPreview = payments.slice(0, 3);

  const stats = details?.stats ?? {
    total_steps: 0,
    mission_success_count: 0,
    total_mission_coins: 0,
  };

  const updateServerImagePermission = async (permissionResult: any) => {
    const granted = !!permissionResult?.granted;
    const status = permissionResult?.status ? String(permissionResult.status) : null;

    const saved = await profileApi.updateImagePermission({
      granted,
      status,
    });

    setPermissions({ image: !!saved.image_permission_granted });
    updateUser({
      imagePermissionGranted: !!saved.image_permission_granted,
      imagePermissionStatus: saved.image_permission_status,
    });

    setDetails((prev) =>
      prev
        ? {
            ...prev,
            profile: {
              ...prev.profile,
              image_permission_granted: !!saved.image_permission_granted,
              image_permission_status: saved.image_permission_status,
            },
          }
        : prev
    );

    return saved;
  };

  const ensureNativeImagePermission = async () => {
    if (details?.profile.image_permission_granted) return true;

    const permissionResult = await rnRequest('AUTH_IMAGE_PERMISSION_REQUEST', {
      openSettingsIfDenied: true,
    });
    const saved = await updateServerImagePermission(permissionResult);

    if (!saved.image_permission_granted) {
      toast.error('사진 / 이미지 권한이 필요합니다. 권한을 허용한 뒤 다시 시도해주세요.');
      return false;
    }

    return true;
  };

  const handleAvatarButtonClick = async () => {
    setAvatarError(null);

    if (!isRnWebViewAvailable()) {
      fileInputRef.current?.click();
      return;
    }

    setIsPickingImage(true);

    try {
      const hasPermission = await ensureNativeImagePermission();
      if (!hasPermission) return;

      const result = await rnRequest('PROFILE_IMAGE_PICK_REQUEST', {
        source: 'gallery',
        maxBytes: MAX_PROFILE_IMAGE_BYTES,
        allowsEditing: true,
        quality: 0.85,
        openSettingsIfDenied: true,
      });

      if (result?.cancelled) return;

      const dataUrl = String(result?.dataUrl || '');
      validateProfileImageDataUrl(dataUrl);

      setAvatarUrl(dataUrl);
      toast.success('갤러리에서 이미지를 선택했어요. 저장 버튼을 누르면 적용됩니다.');
    } catch (e: any) {
      const message = e?.message ? String(e.message) : '이미지를 불러오지 못했습니다.';
      setAvatarError(message);
      toast.error(message);
    } finally {
      setIsPickingImage(false);
    }
  };

  const handleWebAvatarPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;

    if (!f.type.startsWith('image/')) {
      setAvatarError('이미지 파일만 등록할 수 있어요.');
      e.target.value = '';
      return;
    }

    if (f.size > MAX_PROFILE_IMAGE_BYTES) {
      setAvatarError('5MB 이하 이미지만 등록해주세요.');
      e.target.value = '';
      return;
    }

    setAvatarError(null);
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result as string;
      try {
        validateProfileImageDataUrl(dataUrl);
        setAvatarUrl(dataUrl);
      } catch (err: any) {
        setAvatarError(err?.message || '이미지를 등록하지 못했습니다.');
      }
    };
    reader.readAsDataURL(f);
  };

  const handleBirthDateChange = (value: string) => {
    setBirthDate(value);
    setBirthDateError(getBirthDateError(value));
  };

  const refreshPublicAverageForBirthDateChange = async () => {
    clearPublicAverageCaches();

    try {
      const average = await healthcareApi.getAverage();
      writePublicAverageCache({
        userId: user?.id || user?.username,
        average,
      });

      const source = average?.average?.source;
      const requestedAge = average?.average?.requested_test_age;
      console.log('[PROFILE_PUBLIC_AVERAGE_RESYNC]', {
        source,
        requested_test_age: requestedAge,
        gender: average?.average?.gender,
        data_origin: average?.average?.data_origin,
        public_api_called: average?.average?.public_api_called,
        public_api_success: average?.average?.public_api_success,
        is_fallback_value: average?.average?.is_fallback_value,
      });
    } catch (e) {
      console.warn('[PROFILE_PUBLIC_AVERAGE_RESYNC_FAILED]', e);
      throw e;
    }
  };

  const handleSave = async () => {
    const cleanedName = name.trim();

    if (cleanedName.length < 2) {
      toast.error('이름은 2자 이상 입력해주세요.');
      return;
    }

    if (cleanedName.length > 20) {
      toast.error('이름은 20자 이하로 입력해주세요.');
      return;
    }

    const nextBirthDateError = getBirthDateError(birthDate);
    setBirthDateError(nextBirthDateError);

    if (nextBirthDateError) {
      toast.error(nextBirthDateError);
      return;
    }

    const previousBirthDate = details?.profile.birth_date || '';
    const normalizedBirthDate = birthDate || '';
    const birthDateChanged = previousBirthDate !== normalizedBirthDate;

    if (avatarUrl) {
      try {
        validateProfileImageDataUrl(avatarUrl);
      } catch (e: any) {
        toast.error(e?.message || '프로필 이미지를 확인해주세요.');
        return;
      }
    }

    setIsSaving(true);

    try {
      const updated = await profileApi.updateDetails({
        name: cleanedName,
        birth_date: birthDate || undefined,
        profile_image_data_url: avatarUrl,
      });

      setDetails(updated);
      setName(updated.profile.name || cleanedName);
      setBirthDate(updated.profile.birth_date || '');
      setAvatarUrl(updated.profile.profile_image_data_url || null);

      updateUser({
        nickname: updated.profile.name || cleanedName,
        birthDate: updated.profile.birth_date || undefined,
        profileImage: updated.profile.profile_image_data_url || undefined,
      });

      try {
        localStorage.removeItem('profile_avatar_url');
      } catch {
        // 구버전 로컬 이미지 캐시 제거 실패는 무시
      }

      if (birthDateChanged) {
        try {
          await refreshPublicAverageForBirthDateChange();
          toast.success('프로필 저장 후 공공데이터 평균을 새 생년월일 기준으로 갱신했습니다.');
        } catch {
          clearPublicAverageCaches();
          toast.success('프로필은 저장되었습니다. 공공데이터 평균은 신체 분석 화면에서 다시 갱신됩니다.');
        }
      } else {
        toast.success('프로필 세부 정보가 저장되었습니다.');
      }
    } catch (e: any) {
      toast.error(e?.message ? String(e.message) : '프로필 저장에 실패했습니다.');
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) {
    return (
      <div className="h-[100dvh] overflow-y-auto overscroll-contain relative scrollbar-none bg-gradient-to-b from-[hsl(var(--primary)/0.15)] via-[hsl(var(--primary)/0.06)] to-[hsl(var(--level)/0.12)] flex items-center justify-center">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <RefreshCw className="w-4 h-4 animate-spin" />
          프로필 정보를 불러오는 중...
        </div>
      </div>
    );
  }

  return (
    <div className="h-[100dvh] overflow-y-auto overscroll-contain relative scrollbar-none bg-gradient-to-b from-[hsl(var(--primary)/0.18)] via-[hsl(var(--primary)/0.07)] to-[hsl(var(--level)/0.14)]">
      <div className="sticky top-0 z-20 bg-gradient-to-b from-[hsl(var(--primary)/0.08)] to-[hsl(var(--primary)/0.02)] backdrop-blur-md pt-[env(safe-area-inset-top)]">
        <div className="max-w-[430px] mx-auto px-4 h-14 mt-2 flex items-center justify-between">
          <button
            onClick={() => navigate(-1)}
            className="w-9 h-9 -ml-2 rounded-full hover:bg-muted flex items-center justify-center"
            aria-label="뒤로가기"
          >
            <ChevronLeft className="w-5 h-5 text-foreground" />
          </button>
          <h1 className="text-[15px] font-semibold text-foreground">프로필 설정</h1>
          <div className="w-9 h-9" />
        </div>
      </div>

      <div className="max-w-[430px] mx-auto px-4 py-5 space-y-4 pb-24">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-2xl gradient-primary shadow-md p-5 text-primary-foreground"
        >
          <div className="flex items-center gap-2 text-primary-foreground/80">
            <CalendarDays className="w-4 h-4" />
            <span className="text-xs font-medium">업! 바디와 함께한 시간</span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-4xl font-extrabold tracking-tight tabular-nums">{daysWithApp}</span>
            <span className="text-base font-semibold text-primary-foreground/85">일째</span>
          </div>
          <p className="mt-1 text-xs text-primary-foreground/75">{installDateLabel} 부터 함께하고 있어요</p>
        </motion.div>

        <SectionCard
          title="프로필 변경"
          icon={Pencil}
          action={
            <Button
              onClick={handleSave}
              disabled={isSaving || !!birthDateError}
              className="text-sm font-semibold px-5 py-2 rounded-xl shadow-sm"
            >
              {isSaving ? '저장 중...' : '저장'}
            </Button>
          }
        >
          <div className="flex items-center gap-4">
            <div className="relative">
              <div className="w-20 h-20 rounded-full bg-muted overflow-hidden ring-2 ring-border/60 flex items-center justify-center">
                {avatarUrl ? (
                  <img src={avatarUrl} alt="프로필" className="w-full h-full object-cover" />
                ) : (
                  <span className="text-2xl font-bold text-muted-foreground">
                    {name.slice(0, 1) || 'U'}
                  </span>
                )}
              </div>
              <button
                onClick={handleAvatarButtonClick}
                disabled={isPickingImage}
                className="absolute -bottom-1 -right-1 w-8 h-8 rounded-full bg-foreground text-background shadow-md flex items-center justify-center hover:scale-105 transition-transform disabled:opacity-60"
                aria-label="사진 변경"
              >
                {isPickingImage ? <RefreshCw className="w-4 h-4 animate-spin" /> : <Camera className="w-4 h-4" />}
              </button>
              {avatarUrl && (
                <button
                  onClick={() => setAvatarUrl(null)}
                  className="absolute -top-1 -right-1 w-7 h-7 rounded-full bg-destructive text-destructive-foreground shadow-md flex items-center justify-center hover:scale-105 transition-transform"
                  aria-label="사진 삭제"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                className="hidden"
                onChange={handleWebAvatarPick}
              />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-foreground truncate">{name}</p>
              <p className="text-xs text-muted-foreground truncate">{details?.profile.username || user?.username || 'user@upbody.app'}</p>
              <p className="text-[11px] text-muted-foreground mt-1">
                
              </p>
              {avatarError && (
                <p className="text-[11px] text-red-600 font-medium mt-1">
                  {avatarError}
                </p>
              )}
            </div>
          </div>

          <Separator className="my-4" />

          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="pd-name" className="text-xs text-muted-foreground">이름</Label>
              <Input
                id="pd-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="h-11 rounded-xl bg-background"
                placeholder="이름을 입력하세요"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="pd-birth" className="text-xs text-muted-foreground">생년월일</Label>
              <Input
                id="pd-birth"
                type="date"
                value={birthDate}
                onChange={(e) => handleBirthDateChange(e.target.value)}
                max={new Date().toISOString().slice(0, 10)}
                className={`h-11 rounded-xl bg-background ${birthDateError ? 'border-destructive focus-visible:ring-destructive' : ''}`}
              />
              {birthDateError ? (
                <p className="text-[11px] text-destructive font-medium">
                  {birthDateError}
                </p>
              ) : (
                <p className="text-[11px] text-muted-foreground">
                  만 14세 이상만 설정 가능합니다.
                </p>
              )}
            </div>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <Label className="text-xs text-muted-foreground">이메일</Label>
                <span className="text-[10px] font-semibold text-muted-foreground">
                  변경 불가
                </span>
              </div>
              <div className="h-11 rounded-xl bg-muted/60 flex items-center px-3 text-sm text-muted-foreground">
                {details?.profile.username || user?.username || 'user@upbody.app'}
              </div>
            </div>
          </div>
        </SectionCard>

        <SectionCard title="활동 요약" icon={Trophy}>
          <div className="flex items-center gap-3">
            <Stat label="누적 총 걸음 수" value={Number(stats.total_steps || 0).toLocaleString()} sub="앱 DB 기준" />
            <Separator orientation="vertical" className="h-12" />
            <Stat
              label="미션 성공"
              value={`${Number(stats.mission_success_count || 0).toLocaleString()}회`}
              sub={`총 ${Number(stats.total_mission_coins || 0).toLocaleString()} 코인 획득`}
            />
          </div>
        </SectionCard>

        <SectionCard
          title="AI 미션 성공 내역"
          icon={CheckCircle2}
          action={<ViewAllButton disabled={missionHistory.length === 0} onClick={() => setShowMissionsAll(true)} />}
        >
          {missionsPreview.length > 0 ? (
            <ul className="space-y-3">
              {missionsPreview.map((m) => (
                <MissionRow key={m.id} m={m} />
              ))}
            </ul>
          ) : (
            <EmptyList text="아직 완료한 AI 미션이 없습니다." />
          )}
        </SectionCard>

        <SectionCard
          title="내가 작성한 기록"
          icon={NotebookPen}
          action={<ViewAllButton disabled={routineLogs.length === 0} onClick={() => setShowRoutinesAll(true)} />}
        >
          {routinesPreview.length > 0 ? (
            <ul className="space-y-3">
              {routinesPreview.map((r) => (
                <RoutineRow key={r.id} r={r} />
              ))}
            </ul>
          ) : (
            <EmptyList text="아직 내가 작성한 기록 완료 내역이 없습니다." />
          )}
        </SectionCard>

        <SectionCard
          title="결제 내역"
          icon={Receipt}
          action={<ViewAllButton disabled={payments.length === 0} onClick={() => setShowPaymentsAll(true)} />}
        >
          {paymentsPreview.length > 0 ? (
            <ul className="divide-y divide-border/50 -mx-1">
              {paymentsPreview.map((p) => (
                <PaymentRow key={p.id} p={p} />
              ))}
            </ul>
          ) : (
            <EmptyList text="아직 결제 내역이 없습니다." />
          )}
        </SectionCard>

        <p className="text-center text-[12px] text-muted-foreground/80 pt-2">
          업! 바디는 당신을 응원합니다.
        </p>
      </div>

      <Dialog open={showMissionsAll} onOpenChange={setShowMissionsAll}>
        <DialogContent className={DETAIL_DIALOG_CONTENT_CLASS}>
          <DialogHeader className="px-5 py-4 border-b flex-row items-center justify-between space-y-0 gap-2">
            <DialogTitle className="text-base min-w-0 flex-1 flex items-center gap-2">
              <span className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center shrink-0">
                <CheckCircle2 className="w-4 h-4 text-foreground/70" />
              </span>
              <span className="truncate">AI 미션 성공 내역</span>
            </DialogTitle>
            <DialogClose className="shrink-0 text-muted-foreground hover:text-foreground">
              <X className="w-4 h-4" />
              <span className="sr-only">닫기</span>
            </DialogClose>
          </DialogHeader>
          <ScrollArea className="h-[50vh]">
            <ul className="space-y-3 px-4 py-4">
              {missionHistory.map((m) => (
                <MissionRow key={m.id} m={m} />
              ))}
            </ul>
          </ScrollArea>
        </DialogContent>
      </Dialog>

      <Dialog open={showRoutinesAll} onOpenChange={setShowRoutinesAll}>
        <DialogContent className={DETAIL_DIALOG_CONTENT_CLASS}>
          <DialogHeader className="px-5 py-4 border-b flex-row items-center justify-between space-y-0 gap-2">
            <DialogTitle className="text-base min-w-0 flex-1 flex items-center gap-2">
              <span className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center shrink-0">
                <NotebookPen className="w-4 h-4 text-foreground/70" />
              </span>
              <span className="truncate">내가 작성한 기록</span>
            </DialogTitle>
            <DialogClose className="shrink-0 text-muted-foreground hover:text-foreground">
              <X className="w-4 h-4" />
              <span className="sr-only">닫기</span>
            </DialogClose>
          </DialogHeader>
          <ScrollArea className="h-[50vh]">
            <ul className="space-y-3 px-4 py-4">
              {routineLogs.map((r) => (
                <RoutineRow key={r.id} r={r} />
              ))}
            </ul>
          </ScrollArea>
        </DialogContent>
      </Dialog>

      <Dialog open={showPaymentsAll} onOpenChange={setShowPaymentsAll}>
        <DialogContent className="max-w-[340px] p-0 gap-0 max-h-[70vh] overflow-hidden rounded-2xl [&>button]:hidden">
          <DialogHeader className="px-5 py-4 border-b flex-row items-center justify-between space-y-0 gap-2">
            <DialogTitle className="text-base min-w-0 flex-1 flex items-center gap-2">
              <span className="w-8 h-8 rounded-lg bg-muted flex items-center justify-center shrink-0">
                <Receipt className="w-4 h-4 text-foreground/70" />
              </span>
              <span className="truncate">결제 내역</span>
            </DialogTitle>
            <DialogClose className="shrink-0 text-muted-foreground hover:text-foreground">
              <X className="w-4 h-4" />
              <span className="sr-only">닫기</span>
            </DialogClose>
          </DialogHeader>
          <ScrollArea className="h-[50vh]">
            <ul className="divide-y divide-border/50 pl-4 pr-5 py-2">
              {payments.map((p) => (
                <PaymentRow key={p.id} p={p} />
              ))}
            </ul>
          </ScrollArea>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default ProfileDetailsPage;