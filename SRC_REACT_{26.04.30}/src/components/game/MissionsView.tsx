/**
 * 📜 AI 미션 목록 뷰 - 서버 연동 버전
 *
 * 이번 단계 목표
 * - 서버에서 받아온 missions(appStore.missions) 렌더링
 * - refresh-slot / complete-slot API 연결
 * - 완료/재생성 후 서버 상태 재조회
 * - null / 빈 미션 상태 안전 처리
 *
 * 아직 유지하는 것
 * - B1/B2/B3/C1 프론트 상호작용 위젯
 * - 타입별 UI 스타일
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Target,
  Footprints,
  Activity,
  RefreshCw,
  Play,
  Flag,
  CheckCircle2,
  AlertTriangle,
  Ticket,
  ShoppingCart,
  Moon,
  Droplets,
  PenLine,
  Flame,
  Sparkles,
  HelpCircle,
} from "lucide-react";
import { useAppStore } from "@/stores/appStore";
import { useNavigate } from "react-router-dom";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import MissionTimerWidget from "./missions/MissionTimerWidget";
import MissionRoutineWidget from "./missions/MissionRoutineWidget";
import MissionCheckinDialog from "./missions/MissionCheckinDialog";
import { healthcareApi, missionsApi } from "@/services/api";
import type { CurrentMission, MissionSlotCode } from "@/types";
import { toast } from "sonner";
import { useRnBridge } from "@/hooks/useRnBridge";

// ─────────────────────────────────────────────
// 타입 설정
// ─────────────────────────────────────────────
type LocalMissionStatus = "pending" | "in_progress" | "completed" | "ended";

const TYPE_CONFIG: Record<
  MissionSlotCode,
  {
    label: string;
    color: string;
    bgColor: string;
    borderColor: string;
    icon: typeof Activity;
  }
> = {
  A: {
    label: "활동",
    color: "text-blue-400",
    bgColor: "bg-blue-500/15",
    borderColor: "border-blue-400/30",
    icon: Activity,
  },
  B: {
    label: "루틴",
    color: "text-green-400",
    bgColor: "bg-green-500/15",
    borderColor: "border-green-400/30",
    icon: Moon,
  },
  C: {
    label: "기록",
    color: "text-orange-400",
    bgColor: "bg-orange-500/15",
    borderColor: "border-orange-400/30",
    icon: PenLine,
  },
};

const STATUS_CONFIG: Record<
  LocalMissionStatus,
  { label: string; color: string; bgColor: string; borderColor: string }
> = {
  pending: {
    label: "대기",
    color: "text-white/50",
    bgColor: "bg-white/5",
    borderColor: "border-white/10",
  },
  in_progress: {
    label: "진행중",
    color: "text-violet-400",
    bgColor: "bg-violet-500/15",
    borderColor: "border-violet-400/30",
  },
  completed: {
    label: "완료",
    color: "text-emerald-400",
    bgColor: "bg-emerald-500/15",
    borderColor: "border-emerald-400/30",
  },
  ended: {
    label: "종료",
    color: "text-cyan-400",
    bgColor: "bg-cyan-500/10",
    borderColor: "border-cyan-400/20",
  },
};

const getMissionIcon = (missionType: string) => {
  switch (missionType) {
    case "A1_STEP_TARGET":
      return Footprints;
    case "A2_ACTIVE_KCAL_TARGET":
      return Flame;
    case "B1_TIMER_STRETCH":
      return Activity;
    case "B2_SLEEP_PREP":
      return Moon;
    case "B3_ROUTINE_CHECK":
      return Droplets;
    case "C1_HEALTH_CHECKIN":
      return PenLine;
    default:
      return Activity;
  }
};

const normalizeMissionStatus = (
  mission: CurrentMission,
  dailyFreeRegenRemaining: number
): LocalMissionStatus => {
  if (mission.status === "completed") return "completed";

  // refreshed 상태는 보통 current에서 안 잡히겠지만 방어적으로 처리
  if (mission.status === "refreshed") {
    return dailyFreeRegenRemaining <= 0 ? "ended" : "pending";
  }

  if (mission.status === "in_progress") return "in_progress";

  // active는 UI에서 pending으로 보여주기
  if (mission.status === "active") return "pending";

  return "pending";
};

const getSortedMissionSlots = (missions: CurrentMission[]) => {
  const slotOrder: MissionSlotCode[] = ["A", "B", "C"];

  return [...missions].sort((a, b) => {
    const aIndex = slotOrder.indexOf((a.slot_code as MissionSlotCode) || "A");
    const bIndex = slotOrder.indexOf((b.slot_code as MissionSlotCode) || "A");
    return aIndex - bIndex;
  });
};

const buildMissingSlotPlaceholder = (
  slotCode: MissionSlotCode,
  dailyRemaining: number
): CurrentMission => {
  const fallbackType =
    slotCode === "A"
      ? "A1_STEP_TARGET"
      : slotCode === "B"
      ? "B1_TIMER_STRETCH"
      : "C1_HEALTH_CHECKIN";

  return {
    id: -slotCode.charCodeAt(0),
    slot_code: slotCode,
    mission_type: fallbackType,
    title: "",
    description: "",
    status: dailyRemaining <= 0 ? "refreshed" : "active",
    params: {},
    progress: {},
    reward_exp: 0,
    reward_coins: 0,
    reason: "MISSING_SLOT",
  };
};

const MissionsView = () => {
  const navigate = useNavigate();

  const {
    user,
    missions,
    missionCoins,
    dailyMissionRegenCount,
    gameProfile,
    refreshGameState,
    enqueueAchievementCelebration,
    missionInteractionState,
    setMissionInteractionState,
    removeMissionInteractionState,
    pruneMissionInteractionState,
    missionUiRequest,
    setMissionUiRequest,
    clearMissionUiRequest,
  } = useAppStore();

  // 서버 최신값 기준으로 다시 계산할 현재 활동 데이터
  const [currentSteps, setCurrentSteps] = useState(0);
  const [currentCalories, setCurrentCalories] = useState(0);

  const refreshingSlot = missionUiRequest.refreshingSlot;
  const submittingSlot = missionUiRequest.submittingSlot;
  const isUiBusy = !!refreshingSlot || !!submittingSlot;

  const [giveUpTargetSlot, setGiveUpTargetSlot] = useState<MissionSlotCode | null>(null);
  const [completeTargetSlot, setCompleteTargetSlot] = useState<MissionSlotCode | null>(null);

  const [showDailyLimitDialog, setShowDailyLimitDialog] = useState(false);
  const [showReasonDialog, setShowReasonDialog] = useState<CurrentMission | null>(null);
  const [showUseCoinDialog, setShowUseCoinDialog] = useState(false);
  const [pendingRefreshSlot, setPendingRefreshSlot] = useState<MissionSlotCode | null>(null);
  const [showNoCoinDialog, setShowNoCoinDialog] = useState(false);
  const [bNotificationDeniedOnce, setBNotificationDeniedOnce] = useState(false);

  const [pendingCoinAction, setPendingCoinAction] = useState<{
    type: "refresh" | "retry";
    slotCode: MissionSlotCode;
  } | null>(null);

  const { rnRequest, isRnWebViewAvailable } = useRnBridge();

  const dailyRemaining = gameProfile?.daily_free_regen_remaining ?? Math.max(0, 3 - dailyMissionRegenCount);

  const shouldShowCompleteOnlyButton = dailyRemaining > 0 || missionCoins > 0;

  const getCompleteDialogDescription = () => {
    if (dailyRemaining > 0) {
      return '오늘 무료 재생성이 아직 남아있어요. 새 미션을 생성하려면 "무료 재생성 사용 후 성공 처리" 버튼을 누르세요';
    }

    if (missionCoins > 0) {
      return '오늘 무료 재생성을 모두 사용했어요. 새 미션을 생성하려면 "쿠폰 사용 후 성공 처리" 버튼을 누르세요';
    }

    return '오늘 무료 재생성을 모두 사용했어요. 현재 "미션 쿠폰"이 없어 보상만 지급되고 다음 미션은 생성되지 않습니다.';
  };

  const getCompleteOnlyDialogDescription = () => {
    if (dailyRemaining > 0) {
      return '"성공 처리만" 버튼을 누르면 무료 재생성 횟수을 쓰지 않고 보상만 받습니다.';
    }

    if (missionCoins > 0) {
      return '"성공 처리만" 버튼을 누르면 미션 쿠폰을 쓰지 않고 보상만 받습니다.';
    }

    return "보상만 받고 다음 미션은 생성하지 않습니다.";
  };

  const getCompleteDialogConfirmLabel = () => {
    if (dailyRemaining > 0) return "무료 재생성 사용 후 성공 처리";
    if (missionCoins > 0) return "쿠폰 사용 후 성공 처리";
    return "보상만 받고 종료";
  };

  const getCompleteDialogButtonClass = () => {
    // 무료 재생성 있음 → 기존 초록
    if (dailyRemaining > 0) {
      return "bg-emerald-600 hover:bg-emerald-700 text-white";
    }

    // 무료 없음 + 쿠폰 있음 → cyan (종료 UI랑 동일)
    if (missionCoins > 0) {
      return "bg-cyan-600 hover:bg-cyan-700 text-white";
    }

    // 둘 다 없음 →  주확생 (보상만)
    return "bg-gradient-to-r from-amber-500 to-orange-500 text-white";
  };

  const actualMissions = useMemo(() => getSortedMissionSlots(missions), [missions]);

  const sortedMissions = useMemo(() => {
    const bySlot = new Map<MissionSlotCode, CurrentMission>();

    actualMissions.forEach((mission) => {
      const slot = mission.slot_code as MissionSlotCode;
      if (slot === "A" || slot === "B" || slot === "C") {
        bySlot.set(slot, mission);
      }
    });

    return (["A", "B", "C"] as MissionSlotCode[]).map(
      (slot) => bySlot.get(slot) ?? buildMissingSlotPlaceholder(slot, dailyRemaining)
    );
  }, [actualMissions, dailyRemaining]);

  const hasActiveMission = actualMissions.some((m) => m.status === "in_progress");

  // ─────────────────────────────────────────────
  // 서버 재조회
  // ─────────────────────────────────────────────
  const reloadMissionState = useCallback(async () => {
    try {
      const [gameState, healthResult] = await Promise.all([
        refreshGameState(),
        healthcareApi.getLatestFast().catch(() => null),
      ]);

      setCurrentSteps(healthResult?.activity?.steps ?? 0);
      setCurrentCalories(healthResult?.activity?.calories ?? 0);

      const nextMissions = gameState?.missions ?? [];
      const validKeys = nextMissions.map((mission) => `${mission.slot_code}-${mission.id}`);
      pruneMissionInteractionState(validKeys);

    } catch (error) {
      console.error('미션 상태 재조회 실패:', error);
      toast.error('미션 상태를 다시 불러오지 못했습니다.');
    }
  }, [refreshGameState, pruneMissionInteractionState]);

  useEffect(() => {
    reloadMissionState();
  }, [reloadMissionState]);

  // ─────────────────────────────────────────────
  // 도우미 함수
  // ─────────────────────────────────────────────
  const getMissionKey = (mission: CurrentMission) => `${mission.slot_code}-${mission.id}`;

  const updateMissionInteractionState = (
    mission: CurrentMission,
    patch: Partial<{
      completed: boolean;
      checkinText?: string;
      timerCompleted?: boolean;
      checkedCount?: number;
      routineCompleted?: boolean;
      startedAt?: number;
      endsAt?: number;
      uiState?: "idle" | "running" | "waiting" | "ready" | "done";
      currentRound?: number;
    }>
  ) => {
    const key = getMissionKey(mission);
    const prev = missionInteractionState[key] || { completed: false };

    setMissionInteractionState(key, {
      ...prev,
      ...patch,
    });
  };
  const markInteractionCompleted = (
    mission: CurrentMission,
    payload?: {
      checkinText?: string;
      timerCompleted?: boolean;
      checkedCount?: number;
      routineCompleted?: boolean;
    }
  ) => {
    const key = getMissionKey(mission);
    setMissionInteractionState(key, {
      completed: true,
      checkinText: payload?.checkinText,
      timerCompleted: payload?.timerCompleted,
      checkedCount: payload?.checkedCount,
      routineCompleted: payload?.routineCompleted,
    });
  };

  const isInteractionCompleted = (mission: CurrentMission) => {
    const key = getMissionKey(mission);
    return missionInteractionState[key]?.completed === true;
  };

  const getMissionParams = (mission: CurrentMission) => mission.params || {};
  const getMissionProgress = (mission: CurrentMission) => mission.progress || {};

  const canCompleteMission = (mission: CurrentMission): boolean => {
    const params = getMissionParams(mission);

    if (mission.mission_type === "A1_STEP_TARGET") {
      return currentSteps >= Number(params.target_steps || 0);
    }

    if (mission.mission_type === "A2_ACTIVE_KCAL_TARGET") {
      const progress = getMissionProgress(mission);
      const baselineKcal = Number(progress.baseline_kcal ?? 0);
      const liveDeltaKcal = Math.max(currentCalories - baselineKcal, 0);
      const storedDeltaKcal = Number(progress.delta_kcal ?? 0);
      const deltaKcal = Math.max(liveDeltaKcal, storedDeltaKcal);
      const targetKcal = Number(progress.target_kcal ?? params.target_kcal ?? 0);

      return deltaKcal >= targetKcal;
    }

    return isInteractionCompleted(mission);
  };

  const getCompletePayload = (mission: CurrentMission) => {
    const key = getMissionKey(mission);
    const interaction = missionInteractionState[key];

    switch (mission.mission_type) {
      case "B1_TIMER_STRETCH":
      case "B2_SLEEP_PREP":
        return {
          timer_completed: !!interaction?.timerCompleted,
        };

      case "B3_ROUTINE_CHECK":
        return {
          checked_count: Number(interaction?.checkedCount || 0),
          routine_completed: !!interaction?.routineCompleted,
        };

      case "C1_HEALTH_CHECKIN":
        return {
          checkin_text: interaction?.checkinText || "",
        };

      default:
        return {};
    }
  };

  const cancelMissionTimerNotificationIfNeeded = async (mission: CurrentMission | null | undefined) => {
    if (!mission) return;
    if (!isRnWebViewAvailable()) return;

    const isTimerMission =
      mission.mission_type === "B1_TIMER_STRETCH" ||
      mission.mission_type === "B2_SLEEP_PREP" ||
      mission.mission_type === "B3_ROUTINE_CHECK";

    if (!isTimerMission) return;

    try {
      await rnRequest("MISSION_TIMER_NOTIFICATION_CANCEL_REQUEST", {
        userId: user?.id,
        username: user?.username,
        notificationKey: `mission-timer-${getMissionKey(mission)}`,
      });
    } catch (error) {
      console.warn("타이머 알림 취소 실패:", error);
    }
  };

  const ensureBTypeNotificationPermission = async () => {
    // 일반 브라우저 개발 환경에서는 RN 알림 권한 체크를 건너뜀
    if (!isRnWebViewAvailable()) return true;

    try {
      const permission = await rnRequest("AUTH_NOTIFICATION_PERMISSION_REQUEST", {
        openSettingsIfDenied: bNotificationDeniedOnce,
      });

      if (permission?.granted) {
        setBNotificationDeniedOnce(false);
        return true;
      }

      setBNotificationDeniedOnce(true);

      if (permission?.openedSettings) {
        toast.error("알림 권한 설정에서 권한을 허용한 뒤 다시 진행해주세요.");
      } else {
        toast.error("알림 권한이 없어 미션 진행에 실패했습니다.");
      }

      return false;
    } catch (error) {
      console.warn("B타입 알림 권한 확인 실패:", error);
      setBNotificationDeniedOnce(true);
      toast.error("알림 권한이 없어 미션 진행에 실패했습니다.");
      return false;
    }
  };

  const handleAccept = async (slotCode: MissionSlotCode) => {
    try {
      if (refreshingSlot || submittingSlot) return;

      const targetMission = sortedMissions.find(
        (mission) => mission.slot_code === slotCode
      );

      const isBTypeTimerMission =
        slotCode === "B" &&
        (targetMission?.mission_type === "B1_TIMER_STRETCH" ||
          targetMission?.mission_type === "B2_SLEEP_PREP" ||
          targetMission?.mission_type === "B3_ROUTINE_CHECK");

      if (isBTypeTimerMission) {
        const hasNotificationPermission =
          await ensureBTypeNotificationPermission();

        if (!hasNotificationPermission) {
          return;
        }
      }

      setMissionUiRequest({
        refreshingSlot: slotCode,
        submittingSlot: null,
        actionType: "start",
        startedAt: Date.now(),
      });

      await missionsApi.startSlot({
        slot_code: slotCode,
      });

      await reloadMissionState();
    } catch (error: any) {
      console.error("미션 시작 실패:", error);
      toast.error(error?.message || "미션 시작에 실패했습니다.");
    } finally {
      clearMissionUiRequest();
    }
  };

  const doRefreshSlot = async (slotCode: MissionSlotCode, useMissionCoinIfNeeded = false) => {
    try {

      const targetMission = sortedMissions.find((m) => m.slot_code === slotCode);
      await cancelMissionTimerNotificationIfNeeded(targetMission?.status === "in_progress" ? targetMission : null);

      setMissionUiRequest({
        refreshingSlot: slotCode,
        submittingSlot: null,
        actionType: "refresh",
        startedAt: Date.now(),
      });

      const result = await missionsApi.refreshSlot({
        slot_code: slotCode,
        use_mission_coin_if_needed: useMissionCoinIfNeeded,
      });

      if (!result.ok && result.reason === "MISSION_COIN_REQUIRED") {
        setPendingCoinAction({ type: "refresh", slotCode });
        if (missionCoins > 0) {
          setShowUseCoinDialog(true);
        } else {
          setShowNoCoinDialog(true);
        }
        return;
      }

      if (!result.ok) {
        toast.error(result.message || "미션 재생성에 실패했습니다.");
        return;
      }

      toast.success(result.message || "미션이 재생성되었습니다.");
      await reloadMissionState();
    } catch (error: any) {
      console.error("미션 재생성 실패:", error);
      toast.error(error?.message || "미션 재생성에 실패했습니다.");
    } finally {
      clearMissionUiRequest();
    }
  };

  const handleRefresh = async (mission: CurrentMission) => {
    if (refreshingSlot || submittingSlot) return;

    if (mission.status !== "active") return;

    if (dailyRemaining <= 0) {
      setPendingCoinAction({
        type: "refresh",
        slotCode: mission.slot_code as MissionSlotCode,
      });
      setShowDailyLimitDialog(true);
      return;
    }

    setPendingRefreshSlot(mission.slot_code as MissionSlotCode);
  };

  const handleGiveUpConfirm = async () => {
    if (!giveUpTargetSlot) return;

    const slotCode = giveUpTargetSlot;
    setGiveUpTargetSlot(null);

    if (dailyRemaining <= 0) {
      setPendingCoinAction({ type: "refresh", slotCode });
      setShowDailyLimitDialog(true);
      return;
    }

    await doRefreshSlot(slotCode, false);
  };

  const doCompleteSlot = async (
    slotCode: MissionSlotCode,
    regenerateAfterComplete = true
  ) => {
    const mission = sortedMissions.find((m) => m.slot_code === slotCode);
    if (!mission) return;

    const missionKey = `${mission.slot_code}-${mission.id}`;

    try {
      setMissionUiRequest({
        refreshingSlot: null,
        submittingSlot: slotCode,
        actionType: "complete",
        startedAt: Date.now(),
      });

      const result = await missionsApi.completeSlot({
        slot_code: slotCode,
        client_payload: getCompletePayload(mission),
        regenerate_after_complete: regenerateAfterComplete,
      });

      if (!result.ok) {
        toast.error(result.message || "미션 완료 처리에 실패했습니다.");
        return;
      }

      if (!result.completed) {
        toast.warning(result.message || "아직 완료 조건을 충족하지 않았습니다.");
        await reloadMissionState();
        return;
      }

      if (result.new_achievements?.length) {
        enqueueAchievementCelebration(
          result.new_achievements.map((a) => a.achievement_code)
        );
      }

      removeMissionInteractionState(missionKey);

      if (
        isRnWebViewAvailable() &&
        (mission.mission_type === "B1_TIMER_STRETCH" ||
          mission.mission_type === "B2_SLEEP_PREP" ||
          mission.mission_type === "B3_ROUTINE_CHECK")
      ) {
        try {
          await rnRequest("MISSION_TIMER_NOTIFICATION_CANCEL_REQUEST", {
            userId: user?.id,
            username: user?.username,
            notificationKey: `mission-timer-${getMissionKey(mission)}`,
          });
        } catch (error) {
          console.warn("타이머 완료 알림 취소 실패:", error);
        }
      }

      if (!result.next_mission) {
        if (
          result.next_mission_skipped ||
          result.cost_type === "complete_only" ||
          regenerateAfterComplete === false
        ) {
          toast.success(result.message || "미션 완료 및 보상 지급이 완료되었습니다.");
        } else {
          toast.warning(
            result.message ||
              "미션 완료와 보상 지급은 성공했지만 다음 미션 생성에 실패했습니다."
          );
        }

        await reloadMissionState();
        return;
      }

      toast.success(result.message || "미션 완료!");
      await reloadMissionState();
    } catch (error: any) {
      console.error("미션 완료 실패:", error);
      toast.error(error?.message || "미션 완료 처리에 실패했습니다.");
    } finally {
      clearMissionUiRequest();
      setCompleteTargetSlot(null);
    }
  };

  const handleCompleteConfirm = async (regenerateAfterComplete = true) => {
    if (!completeTargetSlot) return;

    const slotCode = completeTargetSlot;
    await doCompleteSlot(slotCode, regenerateAfterComplete);
  };

  const handleRetryMissingSlot = async (slotCode: MissionSlotCode) => {
    try {
      if (refreshingSlot || submittingSlot) return;

      await cancelMissionTimerNotificationIfNeeded(sortedMissions.find((m) => m.slot_code === slotCode));

      setMissionUiRequest({
        refreshingSlot: slotCode,
        submittingSlot: null,
        actionType: "retry",
        startedAt: Date.now(),
      });

      const result = await missionsApi.retrySlot({
        slot_code: slotCode,
      });

      if (!result.ok) {
        toast.error(result.message || "빈 슬롯 미션 재생성에 실패했습니다.");
        return;
      }

      toast.success(result.message || "빈 슬롯 미션을 다시 생성했습니다.");
      await reloadMissionState();
    } catch (error: any) {
      console.error("빈 슬롯 재생성 실패:", error);
      toast.error(error?.message || "빈 슬롯 미션 재생성에 실패했습니다.");
    } finally {
      clearMissionUiRequest();
    }
  };

  const doRetrySlotWithCoin = async (slotCode: MissionSlotCode) => {
    try {
      await cancelMissionTimerNotificationIfNeeded(sortedMissions.find((m) => m.slot_code === slotCode));

      setMissionUiRequest({
        refreshingSlot: slotCode,
        submittingSlot: null,
        actionType: "retry",
        startedAt: Date.now(),
      });

      const result = await missionsApi.retrySlot({
        slot_code: slotCode,
        use_mission_coin_if_needed: true,
      });

      if (!result.ok && result.reason === "MISSION_COIN_REQUIRED") {
        setPendingCoinAction({ type: "retry", slotCode });
        setShowUseCoinDialog(false);

        if (missionCoins > 0) {
          setShowUseCoinDialog(true);
        } else {
          setShowNoCoinDialog(true);
        }
        return;
      }

      if (!result.ok) {
        if (result.reason === "RETRY_GENERATION_FAILED") {
          toast.error(
            result.message || "새 미션 생성에 실패했습니다. 사용한 쿠폰은 복구되었습니다."
          );
          await reloadMissionState();
          return;
        }

        toast.error(result.message || "빈 슬롯 미션 재생성에 실패했습니다.");
        return;
      }

      toast.success(result.message || "미션 쿠폰을 사용해 새 미션을 생성했습니다.");
      await reloadMissionState();
    } catch (error: any) {
      console.error("미션 쿠폰 빈 슬롯 재생성 실패:", error);
      toast.error(error?.message || "빈 슬롯 미션 재생성에 실패했습니다.");
    } finally {
      clearMissionUiRequest();
    }
  };


  const handleInlineUseCoin = (slotCode: MissionSlotCode) => {
    setPendingCoinAction({
      type: "retry",
      slotCode,
    });

    if (missionCoins > 0) {
      setShowUseCoinDialog(true);
    } else {
      setShowNoCoinDialog(true);
    }
  };

  const handleUseCoinConfirm = () => {
    setShowDailyLimitDialog(false);

    if (missionCoins > 0) {
      setShowUseCoinDialog(true);
    } else {
      setShowNoCoinDialog(true);
    }
  };

  const handleCoinUseYes = async () => {
    if (!pendingCoinAction) return;
    if (refreshingSlot || submittingSlot) return;

    setShowUseCoinDialog(false);

    if (pendingCoinAction.type === "retry") {
      await doRetrySlotWithCoin(pendingCoinAction.slotCode);
    } else {
      await doRefreshSlot(pendingCoinAction.slotCode, true);
    }

    setPendingCoinAction(null);
  };

  // ─────────────────────────────────────────────
  // 타입별 인터랙션 UI
  // ─────────────────────────────────────────────
  const renderInteractionUI = (mission: CurrentMission) => {
    if (mission.status !== "in_progress") return null;

    const params = getMissionParams(mission);

    switch (mission.mission_type) {
      case "A1_STEP_TARGET": {
        const target = Number(params.target_steps || 0);
        const pct = target > 0 ? Math.min(100, (currentSteps / target) * 100) : 0;

        return (
          <div className="mt-2">
            <div className="flex items-center justify-between text-[10px] mb-1">
              <span className="text-blue-300 font-mono">{currentSteps.toLocaleString()}보</span>
              <span className="text-white/40">{target.toLocaleString()}보</span>
            </div>
            <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
              <motion.div
                className="h-full bg-gradient-to-r from-blue-500 to-cyan-500 rounded-full"
                initial={{ width: 0 }}
                animate={{ width: `${pct}%` }}
                transition={{ duration: 0.4 }}
              />
            </div>
          </div>
        );
      }

      case "A2_ACTIVE_KCAL_TARGET": {
        const progress = getMissionProgress(mission);
        const baselineKcal = Number(progress.baseline_kcal ?? 0);
        const currentKcal = Math.max(Number(progress.current_kcal ?? 0), currentCalories);
        const liveDeltaKcal = Math.max(currentCalories - baselineKcal, 0);
        const storedDeltaKcal = Number(progress.delta_kcal ?? 0);
        const deltaKcal = Math.max(liveDeltaKcal, storedDeltaKcal);
        const target = Number(progress.target_kcal ?? params.target_kcal ?? 0);
        const pct = target > 0 ? Math.min(100, (deltaKcal / target) * 100) : 0;

        return (
          <div className="mt-2">
            <div className="flex items-center justify-between text-[10px] mb-1">
              <span className="text-orange-300 font-mono">
                +{deltaKcal.toLocaleString()}kcal
              </span>
              <span className="text-white/40">{target.toLocaleString()}kcal</span>
            </div>

            <div className="text-[10px] text-white/35 mb-1">
              현재 누적 {currentKcal.toLocaleString()}kcal · 기준 {baselineKcal.toLocaleString()}kcal
            </div>

            <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
              <motion.div
                className="h-full bg-gradient-to-r from-orange-500 to-yellow-500 rounded-full"
                initial={{ width: 0 }}
                animate={{ width: `${pct}%` }}
                transition={{ duration: 0.4 }}
              />
            </div>
          </div>
        );
      }

      case "B1_TIMER_STRETCH": {
        const key = getMissionKey(mission);
        const interaction = missionInteractionState[key];

        return (
          <div className="mt-2">
            <MissionTimerWidget
              minutes={Number(params.duration_min || 5)}
              label="스트레칭"
              completed={isInteractionCompleted(mission)}
              startedAt={interaction?.startedAt}
              endsAt={interaction?.endsAt}
              uiState={(interaction?.uiState as "idle" | "running" | "done") ?? "idle"}
              notificationKey={`mission-timer-${getMissionKey(mission)}`}
              onStart={({ startedAt, endsAt, uiState }) =>
                updateMissionInteractionState(mission, {
                  startedAt,
                  endsAt,
                  uiState,
                  completed: false,
                  timerCompleted: false,
                })
              }
              onComplete={() =>
                updateMissionInteractionState(mission, {
                  completed: true,
                  timerCompleted: true,
                  uiState: "done",
                })
              }
            />
          </div>
        );
      }

      case "B2_SLEEP_PREP": {
        const key = getMissionKey(mission);
        const interaction = missionInteractionState[key];

        return (
          <div className="mt-2">
            <MissionTimerWidget
              minutes={Number(params.duration_min || 5)}
              label="휴식"
              completed={isInteractionCompleted(mission)}
              startedAt={interaction?.startedAt}
              endsAt={interaction?.endsAt}
              uiState={(interaction?.uiState as "idle" | "running" | "done") ?? "idle"}
              notificationKey={`mission-timer-${getMissionKey(mission)}`}
              onStart={({ startedAt, endsAt, uiState }) =>
                updateMissionInteractionState(mission, {
                  startedAt,
                  endsAt,
                  uiState,
                  completed: false,
                  timerCompleted: false,
                })
              }
              onComplete={() =>
                updateMissionInteractionState(mission, {
                  completed: true,
                  timerCompleted: true,
                  uiState: "done",
                })
              }
            />
          </div>
        );
      }

      case "B3_ROUTINE_CHECK": {
        const key = getMissionKey(mission);
        const interaction = missionInteractionState[key];

        return (
          <div className="mt-2">
            <MissionRoutineWidget
              totalRounds={Number(params.repeat_count || 3)}
              intervalMinutes={Number(params.interval_min || 10)}
              completed={isInteractionCompleted(mission)}
              startedAt={interaction?.startedAt}
              endsAt={interaction?.endsAt}
              currentRound={interaction?.currentRound ?? 0}
              uiState={
                (interaction?.uiState as "idle" | "waiting" | "ready" | "done") ?? "idle"
              }
              notificationKey={`mission-timer-${getMissionKey(mission)}`}
              onStateChange={(payload) =>
                updateMissionInteractionState(mission, {
                  startedAt: payload.startedAt,
                  endsAt: payload.endsAt,
                  currentRound: payload.currentRound,
                  checkedCount: payload.checkedCount,
                  uiState: payload.uiState,
                  completed: false,
                  routineCompleted: false,
                })
              }
              onComplete={(payload) =>
                updateMissionInteractionState(mission, {
                  completed: true,
                  checkedCount: payload.checkedCount,
                  routineCompleted: payload.routineCompleted,
                  currentRound: payload.checkedCount,
                  uiState: "done",
                  startedAt: undefined,
                  endsAt: undefined,
                })
              }
            />
          </div>
        );
      }

        case "C1_HEALTH_CHECKIN":
          return (
            <div className="mt-2">
              <MissionCheckinDialog
                completed={isInteractionCompleted(mission)}
                minLength={mission.params?.min_length ?? 15}
                onComplete={(text) =>
                  markInteractionCompleted(mission, { checkinText: text })
                }
              />
            </div>
          );

      default:
        return null;
    }
  };

  // ─────────────────────────────────────────────
  // 빈 상태
  // ─────────────────────────────────────────────
  if (!sortedMissions || sortedMissions.length === 0) {
    return (
      <div className="flex-1 overflow-y-auto px-5 pb-4">
        <div className="rounded-2xl border border-white/10 bg-white/5 backdrop-blur-sm p-5 text-center">
          <div className="w-14 h-14 mx-auto rounded-2xl bg-violet-500/15 border border-violet-400/20 flex items-center justify-center mb-3">
            <Sparkles className="w-7 h-7 text-violet-300" />
          </div>

          <p className="text-white font-semibold">현재 표시할 AI 미션이 없습니다</p>
          <p className="text-white/50 text-sm mt-2">
            미션이 삭제되었거나 아직 생성되지 않았을 수 있습니다.
          </p>
        </div>
      </div>
    );
  }

  // ─────────────────────────────────────────────
  // 렌더
  // ─────────────────────────────────────────────
  return (
    <div className="flex-1 overflow-y-auto px-5 pb-4">
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="space-y-3">
        {/* 헤더 */}
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <svg width="0" height="0" className="absolute">
              <defs>
                <linearGradient id="targetGradientHeader" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#fde68a" />
                  <stop offset="50%" stopColor="#facc15" />
                  <stop offset="100%" stopColor="#f59e0b" />
                </linearGradient>
              </defs>
            </svg>

            <Target
              className="w-5 h-5 drop-shadow-[0_0_6px_rgba(250,204,21,0.35)]"
              stroke="url(#targetGradientHeader)"
            />

            <h2 className="text-lg font-bold text-white">오늘의 AI 미션</h2>
          </div>

          <span className="text-xs text-white/50 bg-white/10 px-2.5 py-1 rounded-full border border-white/10">
            하루 무료 재생성 {dailyRemaining}/3
          </span>
        </div>

        {/* 타입 범례 */}
        <div className="flex items-center gap-2 mb-1">
          {Object.entries(TYPE_CONFIG).map(([key, cfg]) => (
            <div
              key={key}
              className={`flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full ${cfg.bgColor} border ${cfg.borderColor} ${cfg.color}`}
            >
              <cfg.icon className="w-3 h-3" />
              <span>{cfg.label}</span>
            </div>
          ))}
        </div>

        {sortedMissions.map((mission, index) => {
          const slotCode = mission.slot_code as MissionSlotCode;
          const typeConfig = TYPE_CONFIG[slotCode] || TYPE_CONFIG.A;
          const status = normalizeMissionStatus(mission, dailyRemaining);
          const statusConfig = STATUS_CONFIG[status];
          const Icon = getMissionIcon(mission.mission_type);

          const isRefreshing = refreshingSlot === slotCode;
          const isSubmitting = submittingSlot === slotCode;
          const isDisabledByActive = hasActiveMission && mission.status === "active";
          const canComplete = mission.status === "in_progress" && canCompleteMission(mission);
          const isMissingSlot = mission.reason === "MISSING_SLOT" && mission.id < 0;


          if (isMissingSlot && dailyRemaining > 0) {
            return (
              <motion.div
                key={`missing-${slotCode}-${index}`}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: index * 0.08 }}
                className="relative overflow-hidden rounded-2xl p-5 border backdrop-blur-sm bg-amber-500/5 border-amber-400/20"
              >
                <AnimatePresence>
                  {isRefreshing && (
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="absolute inset-0 z-10 rounded-2xl bg-black/50 backdrop-blur-sm flex items-center justify-center"
                    >
                      <div className="flex items-center gap-2 text-white">
                        <motion.div
                          animate={{ rotate: 360 }}
                          transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                        >
                          <RefreshCw className="w-5 h-5" />
                        </motion.div>
                        <span className="text-sm font-medium">미션 생성 중...</span>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>

                <div className="flex flex-col items-center text-center gap-3">
                  <div className="w-12 h-12 rounded-xl bg-amber-500/15 border border-amber-400/20 flex items-center justify-center">
                    <AlertTriangle className="w-6 h-6 text-amber-300" />
                  </div>

                  <div>
                    <p className="text-sm font-bold text-white">
                      {typeConfig.label} 슬롯에 진행 중인 미션이 없습니다
                    </p>
                    <p className="text-xs text-white/40 mt-1">
                      새로운 미션을 진행하고 싶으면
                      <br />
                      아래 버튼으로 미션을 생성하세요.
                    </p>
                  </div>

                  <motion.button
                    whileTap={!isUiBusy ? { scale: 0.95 } : undefined}
                    disabled={isUiBusy}
                    onClick={() => !isUiBusy && handleRetryMissingSlot(slotCode)}
                    className={`w-full flex items-center justify-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold border ${
                      isUiBusy
                        ? "bg-white/5 text-white/25 border-white/10 cursor-not-allowed"
                        : "bg-gradient-to-r from-amber-500 to-orange-500 text-white border border-white/20 shadow-[0_0_15px_rgba(245,158,11,0.3)]"
                    }`}
                  >
                    {isRefreshing ? (
                      <>
                        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                        생성 중...
                      </>
                    ) : (
                      <>
                        <RefreshCw className="w-3.5 h-3.5" />
                        새 미션 생성하기
                      </>
                    )}
                  </motion.button>
                </div>
              </motion.div>
            );
          }
          // 종료 UI: 무료 재생성이 없고, 이 슬롯이 더 이상 자동 재생성 없이 비어 있거나 막힌 경우용
          // 지금 current에 ended 슬롯이 따로 안 올 수 있어서, 실제 ended UI는 최소화해서 유지
          if (isMissingSlot && dailyRemaining <= 0) {
            return (
              <motion.div
                key={`${mission.id}-${slotCode}-${index}`}
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: index * 0.08 }}
                className="relative overflow-hidden rounded-2xl p-5 border backdrop-blur-sm bg-cyan-500/5 border-cyan-400/20"
              >
                <AnimatePresence>
                  {isRefreshing && (
                    <motion.div
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="absolute inset-0 z-10 rounded-2xl bg-black/50 backdrop-blur-sm flex items-center justify-center"
                    >
                      <div className="flex items-center gap-2 text-white">
                        <motion.div
                          animate={{ rotate: 360 }}
                          transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                        >
                          <RefreshCw className="w-5 h-5" />
                        </motion.div>
                        <span className="text-sm font-medium">
                          {missionUiRequest.actionType === "retry"
                            ? "미션 생성 중..."
                            : "미션 재생성 중..."}
                        </span>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>

                <div className="flex flex-col items-center text-center gap-3">
                  <div className="w-12 h-12 rounded-xl bg-cyan-500/15 border border-cyan-400/20 flex items-center justify-center">
                    <typeConfig.icon className={`w-6 h-6 ${typeConfig.color}`} />
                  </div>

                  <div>
                    <p className="text-sm font-bold text-white">{typeConfig.label} 미션이 종료되었습니다</p>
                    <p className="text-xs text-white/40 mt-1">
                      추가 미션을 진행하고 싶으면
                      <br />
                      <span className="text-cyan-400 font-semibold">미션 쿠폰</span>을 사용하세요
                    </p>
                  </div>

                  <div className="flex flex-col gap-2 w-full">
                    <motion.button
                      whileTap={!isUiBusy ? { scale: 0.95 } : undefined}
                      disabled={isUiBusy}
                      onClick={() => !isUiBusy && handleInlineUseCoin(slotCode)}
                      className={`flex items-center justify-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold border ${
                        isUiBusy
                          ? "bg-white/5 text-white/25 border-white/10 cursor-not-allowed"
                          : "bg-gradient-to-r from-cyan-600 to-blue-600 text-white border-white/20 shadow-[0_0_15px_rgba(6,182,212,0.3)]"
                      }`}
                    >
                      {isRefreshing && missionUiRequest.actionType === "retry" ? (
                        <>
                          <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                          미션 생성 중...
                        </>
                      ) : (
                        <>
                          <Ticket className="w-3.5 h-3.5" />
                          미션 쿠폰 사용
                        </>
                      )}
                    </motion.button>

                    <motion.button
                      whileTap={!isUiBusy && dailyRemaining > 0 ? { scale: 0.95 } : undefined}
                      disabled={dailyRemaining <= 0 || isUiBusy}
                      onClick={() => !isUiBusy && dailyRemaining > 0 && setPendingRefreshSlot(slotCode)}
                      className={`flex items-center justify-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold border transition-all ${
                        dailyRemaining > 0 && !isUiBusy
                          ? "bg-gradient-to-r from-emerald-600 to-green-600 text-white border-white/20 shadow-[0_0_15px_rgba(16,185,129,0.3)]"
                          : "bg-white/5 text-white/25 border-white/10 cursor-not-allowed"
                      }`}
                    >
                      {isRefreshing && missionUiRequest.actionType === "refresh" ? (
                        <>
                          <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                          재생성 중...
                        </>
                      ) : (
                        <>
                          <RefreshCw className="w-3.5 h-3.5" />
                          무료 미션 재생성 ({dailyRemaining}/3)
                        </>
                      )}
                    </motion.button>
                  </div>
                </div>
              </motion.div>
            );
          }

          return (
            <motion.div
              key={`${mission.id}-${slotCode}-${index}`}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: isDisabledByActive ? 0.5 : 1, x: 0 }}
              transition={{ delay: index * 0.08 }}
              className={`relative rounded-2xl p-4 border backdrop-blur-sm ${statusConfig.bgColor} ${statusConfig.borderColor}`}
            >
              <AnimatePresence>
                {(isRefreshing || isSubmitting) && (
                  <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="absolute inset-0 z-10 rounded-2xl bg-black/50 backdrop-blur-sm flex items-center justify-center"
                  >
                    <div className="flex items-center gap-2 text-white">
                      <motion.div
                        animate={{ rotate: 360 }}
                        transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                      >
                        <RefreshCw className="w-5 h-5" />
                      </motion.div>
                      <span className="text-sm font-medium">
                        {missionUiRequest.actionType === "start"
                          ? "미션 시작 중..."
                          : isRefreshing
                          ? "미션 재생성 중..."
                          : "미션 처리 중..."}
                      </span>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              <div className="flex items-start gap-3">
                <div
                  className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 ${
                    mission.status === "completed"
                      ? "bg-emerald-500/20 border border-emerald-400/30"
                      : `${typeConfig.bgColor} border ${typeConfig.borderColor}`
                  }`}
                >
                  {mission.status === "completed" ? (
                    <CheckCircle2 className="w-5 h-5 text-emerald-300" />
                  ) : (
                    <Icon className={`w-5 h-5 ${typeConfig.color}`} />
                  )}
                </div>

                <div className="flex-1 min-w-0">
                  <div className="flex flex-col gap-1.5 min-w-0">
                    <h3
                      className={`font-semibold text-sm leading-snug break-words ${
                        mission.status === "completed" ? "text-emerald-300 line-through" : "text-white"
                      }`}
                    >
                      {mission.title}
                    </h3>

                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span
                        className={`w-fit text-[9px] px-1.5 py-0.5 rounded-full font-bold ${typeConfig.bgColor} border ${typeConfig.borderColor} ${typeConfig.color}`}
                      >
                        {typeConfig.label}
                      </span>

                      <span
                        className={`w-fit text-[9px] px-1.5 py-0.5 rounded-full font-medium ${statusConfig.bgColor} border ${statusConfig.borderColor} ${statusConfig.color}`}
                      >
                        {statusConfig.label}
                      </span>
                    </div>
                  </div>

                  <p className="text-xs text-white/55 mt-1 leading-relaxed">{mission.description}</p>

                  {/* 보상 */}
                  <div className="flex items-center gap-2 mt-2">
                    <div className="text-[10px] text-cyan-300 bg-cyan-500/10 border border-cyan-500/20 px-2 py-1 rounded-full">
                      EXP +{mission.reward_exp}
                    </div>
                    <div className="text-[10px] text-yellow-300 bg-yellow-500/10 border border-yellow-500/20 px-2 py-1 rounded-full">
                      코인 +{mission.reward_coins}
                    </div>
                    <div className="flex-1" />
                    <motion.button
                      whileTap={!isDisabledByActive && !isUiBusy ? { scale: 0.95 } : undefined}
                      disabled={isDisabledByActive || isUiBusy}
                      onClick={() => {
                        if (isDisabledByActive || isUiBusy) return;
                        setShowReasonDialog(mission);
                      }}
                      className={`text-[10px] font-semibold border px-2 py-1 rounded-full transition-all ${
                        isDisabledByActive || isUiBusy
                          ? "bg-white/5 text-white/25 border-white/10 cursor-not-allowed"
                          : "text-white bg-gradient-to-r from-emerald-600 to-green-600 border-white/20 hover:from-emerald-500 hover:to-green-500 shadow-[0_0_10px_rgba(16,185,129,0.2)]"
                      }`}
                    >
                      AI 추천 이유
                    </motion.button>
                  </div>

                  {/* 인터랙션 UI */}
                  {renderInteractionUI(mission)}

                  {/* 버튼 영역 */}
                  <div className="flex items-center gap-2 mt-3">
                    {mission.status === "active" && (
                      <>
                        <motion.button
                          whileTap={!isDisabledByActive ? { scale: 0.95 } : undefined}
                          disabled={isDisabledByActive || !!refreshingSlot || !!submittingSlot}
                          onClick={() => handleAccept(slotCode)}
                          className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold border transition-all ${
                            isDisabledByActive
                              ? "bg-white/5 text-white/25 border-white/10 cursor-not-allowed"
                              : "bg-gradient-to-r from-violet-600 to-purple-600 text-white border-white/20 shadow-[0_0_15px_rgba(139,92,246,0.3)]"
                          }`}
                        >
                          <Play className="w-3.5 h-3.5" />
                          진행하기
                        </motion.button>

                        <motion.button
                          whileTap={!isDisabledByActive ? { scale: 0.95 } : undefined}
                          disabled={isDisabledByActive || !!refreshingSlot || !!submittingSlot}
                          onClick={() => handleRefresh(mission)}
                          className={`px-3 py-2 rounded-xl text-xs font-semibold border transition-all ${
                            isDisabledByActive
                              ? "bg-white/5 text-white/25 border-white/10 cursor-not-allowed"
                              : "bg-white/10 text-white border-white/15 hover:bg-white/15"
                          }`}
                        >
                          <RefreshCw className="w-3.5 h-3.5" />
                        </motion.button>
                      </>
                    )}

                    {mission.status === "in_progress" && (
                      <>
                        <motion.button
                          whileTap={{ scale: 0.95 }}
                          disabled={!canComplete || !!submittingSlot || !!refreshingSlot}
                          onClick={() => setCompleteTargetSlot(slotCode)}
                          className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold border transition-all ${
                            canComplete
                              ? "bg-gradient-to-r from-emerald-600 to-green-600 text-white border-white/20 shadow-[0_0_15px_rgba(16,185,129,0.3)]"
                              : "bg-white/5 text-white/25 border-white/10 cursor-not-allowed"
                          }`}
                        >
                          <Flag className="w-3.5 h-3.5" />
                          미션 성공
                        </motion.button>
                        

                        <motion.button
                          whileTap={{ scale: 0.95 }}
                          disabled={!!submittingSlot || !!refreshingSlot}
                          onClick={() => setGiveUpTargetSlot(slotCode)}
                          className="px-3 py-2 rounded-xl text-xs font-semibold border bg-red-500/10 text-red-300 border-red-500/20 hover:bg-red-500/15 transition-all"
                        >
                          포기
                        </motion.button>
                      </>
                    )}

                    {mission.status === "completed" && (
                      <div className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-xl text-xs font-semibold border bg-emerald-500/10 text-emerald-300 border-emerald-500/20">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        미션 완료
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </motion.div>
          );
        })}
        <p className="text-center text-[12px] text-white/40 pt-2">
          업! 바디는 당신을 응원합니다.
        </p>
      </motion.div>

      {/* 포기 확인 */}
      <AlertDialog open={!!giveUpTargetSlot} onOpenChange={(open) => !open && setGiveUpTargetSlot(null)}>
        <AlertDialogContent className="bg-slate-900 border-white/10">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-white">미션을 포기할까요?</AlertDialogTitle>
            <AlertDialogDescription className="text-white/60">
              포기하면 해당 슬롯의 미션이 재생성됩니다.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              onClick={() => setGiveUpTargetSlot(null)}
              className="bg-white/5 text-white border-white/10 hover:bg-white/10"
            >
              아니요
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleGiveUpConfirm}
              className="bg-red-600 hover:bg-red-700 text-white"
            >
              포기하기
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* 완료 확인 */}
      <AlertDialog open={!!completeTargetSlot} onOpenChange={(open) => !open && setCompleteTargetSlot(null)}>
        <AlertDialogContent className="bg-slate-900 border-white/10">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-white">미션을 완료 처리할까요?</AlertDialogTitle>
              <AlertDialogDescription className="text-white/60 space-y-2">
                <span className="block">{getCompleteDialogDescription()}</span>

                {shouldShowCompleteOnlyButton && (
                  <span className="block text-xs text-white/45">
                    {getCompleteOnlyDialogDescription()}
                  </span>
                )}
              </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter className="gap-2 sm:space-x-0">
            <AlertDialogCancel
              onClick={() => setCompleteTargetSlot(null)}
              className="bg-white/5 text-white border-white/10 hover:bg-white/10"
            >
              취소
            </AlertDialogCancel>
            {shouldShowCompleteOnlyButton && (
              <AlertDialogAction
                onClick={() => handleCompleteConfirm(false)}
                disabled={!!refreshingSlot || !!submittingSlot}
                className="bg-gradient-to-r from-amber-500 to-orange-500 hover:from-amber-400 hover:to-orange-400 text-white border border-amber-300/30 shadow-[0_0_14px_rgba(245,158,11,0.35)] disabled:opacity-50"
              >
                성공 처리만
              </AlertDialogAction>
            )}
            <AlertDialogAction
              onClick={() => handleCompleteConfirm(true)}
              disabled={!!refreshingSlot || !!submittingSlot}
              className={`${getCompleteDialogButtonClass()} disabled:opacity-50`}
            >
              {getCompleteDialogConfirmLabel()}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* 재생성 확인 */}
      <AlertDialog open={!!pendingRefreshSlot} onOpenChange={(open) => !open && setPendingRefreshSlot(null)}>
        <AlertDialogContent className="bg-slate-900 border-white/10">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-white">미션을 재생성할까요?</AlertDialogTitle>
            <AlertDialogDescription className="text-white/60">
              현재 미션이 삭제되고 새로운 미션이 생성됩니다.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-white/10 text-white border-white/10 hover:bg-white/20">
              아니요
            </AlertDialogCancel>
            <AlertDialogAction
              className="bg-emerald-600 hover:bg-emerald-700 text-white"
              onClick={() => {
                if (pendingRefreshSlot) {
                  doRefreshSlot(pendingRefreshSlot);
                }
                setPendingRefreshSlot(null);
              }}
            >
              예
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>


      {/* 하루 무료 재생성 소진 */}
      <AlertDialog open={showDailyLimitDialog} onOpenChange={setShowDailyLimitDialog}>
        <AlertDialogContent className="bg-slate-900 border-white/10">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-white">오늘 무료 재생성을 모두 사용했어요</AlertDialogTitle>
            <AlertDialogDescription className="text-white/60">
              추가 미션을 진행하려면 미션 쿠폰을 사용해야 합니다.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-white/5 text-white border-white/10 hover:bg-white/10">
              취소
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleUseCoinConfirm}
              className="bg-cyan-600 hover:bg-cyan-700 text-white"
            >
              미션 쿠폰 사용
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* 미션 쿠폰 사용 확인 */}
      <AlertDialog open={showUseCoinDialog} onOpenChange={setShowUseCoinDialog}>
        <AlertDialogContent className="bg-slate-900 border-white/10">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-white">미션 쿠폰을 사용할까요?</AlertDialogTitle>
            <AlertDialogDescription className="text-white/60">
              쿠폰 1개를 사용해서 해당 슬롯의 미션을 다시 생성합니다.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-white/5 text-white border-white/10 hover:bg-white/10">
              아니요
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleCoinUseYes}
              disabled={!!refreshingSlot || !!submittingSlot}
              className="bg-cyan-600 hover:bg-cyan-700 text-white disabled:opacity-50"
            >
              예
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* 코인 부족 */}
      <AlertDialog open={showNoCoinDialog} onOpenChange={setShowNoCoinDialog}>
        <AlertDialogContent className="bg-slate-900 border-white/10">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-white">미션 쿠폰이 부족합니다</AlertDialogTitle>
            <AlertDialogDescription className="text-white/60">
              미션 쿠폰을 구매하려면 결제 페이지로 이동해주세요.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="bg-white/5 text-white border-white/10 hover:bg-white/10">
              닫기
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => navigate("/mission-coin-shop")}
              className="bg-violet-600 hover:bg-violet-700 text-white"
            >
              <ShoppingCart className="w-4 h-4 mr-1" />
              결제 페이지로
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {/* AI 추천 이유 팝업 */}
      <Dialog open={!!showReasonDialog} onOpenChange={(open) => !open && setShowReasonDialog(null)}>
        <DialogContent className="bg-slate-900 border-white/10 max-w-[360px] rounded-2xl [&>button]:text-white [&>button]:opacity-100 [&>button]:ring-0 [&>button]:ring-offset-0 [&>button:focus]:ring-0 [&>button:focus]:ring-offset-0 [&>button]:border-0 [&>button]:bg-transparent [&>button]:shadow-none">
          <DialogHeader>
            <DialogTitle className="text-white text-base flex items-center gap-2">
              <span className="flex items-center justify-center w-6 h-6 rounded-full bg-gradient-to-r from-emerald-600 to-green-600 border border-white/20 shadow-[0_0_10px_rgba(16,185,129,0.2)]">
                <Sparkles className="w-3.5 h-3.5 text-white" />
              </span>
              AI가 이렇게 추천하는 이유
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            {showReasonDialog && (
              <>
                <div className="text-sm font-semibold text-white">
                  {showReasonDialog.title}
                </div>
                <div className="text-xs text-white/70 leading-relaxed bg-white/5 rounded-xl p-3 border border-white/10">
                  {showReasonDialog.reason && showReasonDialog.reason !== "MISSING_SLOT"
                    ? showReasonDialog.reason
                    : "-"}
                </div>
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>


    </div>
  );
};

export default MissionsView;