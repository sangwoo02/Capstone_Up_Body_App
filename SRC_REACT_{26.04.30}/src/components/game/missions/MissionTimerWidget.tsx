/**
 * ⏱️ 타이머 위젯 (B1_TIMER_STRETCH, B2_SLEEP_PREP)
 * 시작 → 카운트다운 → 자동 완료 처리
 *
 * 변경 포인트
 * 1) completed / startedAt / endsAt / uiState prop 기반으로 외부 상태와 동기화
 * 2) 탭 이동 후 돌아와도 endsAt 기준으로 남은 시간 복원
 * 3) 타이머 종료 시 onComplete 자동 호출
 * 4) done 상태에서는 "완료됨" 표시만 렌더링
 * 5) RN(WebView) 환경에서는 타이머 종료 시 로컬 알림 예약
 * 6) 앱이 켜져 있는 상태에서 타이머가 끝나면 즉시 알림/진동 실행
 * 7) RN 예약 알림에 targetTimeMs를 같이 전달하여 DATE trigger 사용 가능
 */
import { useState, useEffect, useRef, useCallback } from "react";
import { motion } from "framer-motion";
import { Play, CheckCircle2, Timer } from "lucide-react";
import { useRnBridge } from "@/hooks/useRnBridge";
import { useAppStore } from "@/stores/appStore";

interface MissionTimerWidgetProps {
  minutes: number;
  label: string;
  completed?: boolean;
  startedAt?: number;
  endsAt?: number;
  uiState?: "idle" | "running" | "done";
  notificationKey: string;
  onStart: (payload: {
    startedAt: number;
    endsAt: number;
    uiState: "running";
  }) => void;
  onComplete: () => void;
}

const MissionTimerWidget = ({
  minutes,
  label,
  completed = false,
  startedAt,
  endsAt,
  uiState = "idle",
  notificationKey,
  onStart,
  onComplete,
}: MissionTimerWidgetProps) => {
  const { rnRequest, isRnWebViewAvailable } = useRnBridge();
  const currentUser = useAppStore((state) => state.user);

  const [state, setState] = useState<"idle" | "running" | "done">(() => {
    if (completed) return "done";
    if (uiState === "running" && endsAt && endsAt > Date.now()) {
      return "running";
    }
    if (uiState === "done") return "done";
    return "idle";
  });

  const [secondsLeft, setSecondsLeft] = useState(() => {
    if (completed) return 0;
    if (uiState === "running" && endsAt) {
      return Math.max(0, Math.ceil((endsAt - Date.now()) / 1000));
    }
    return minutes * 60;
  });

  const completeCalledRef = useRef(completed);
  const scheduledEndsAtRef = useRef<number | null>(null);
  const hadRunningStateRef = useRef(false);

  useEffect(() => {
    if (completed) {
      setState("done");
      setSecondsLeft(0);
      completeCalledRef.current = true;
      hadRunningStateRef.current = false;
      return;
    }

    if (uiState === "running" && endsAt) {
      const remain = Math.max(0, Math.ceil((endsAt - Date.now()) / 1000));

      if (remain <= 0) {
        setState("done");
        setSecondsLeft(0);
      } else {
        setState("running");
        setSecondsLeft(remain);
      }

      completeCalledRef.current = false;
      return;
    }

    if (uiState === "done") {
      setState("done");
      setSecondsLeft(0);
      completeCalledRef.current = true;
      hadRunningStateRef.current = false;
      return;
    }

    setState("idle");
    setSecondsLeft(minutes * 60);
    completeCalledRef.current = false;
    hadRunningStateRef.current = false;
  }, [minutes, completed, startedAt, endsAt, uiState]);

  useEffect(() => {
    if (state === "running") {
      hadRunningStateRef.current = true;
    }

    if (state === "idle") {
      hadRunningStateRef.current = false;
    }
  }, [state]);

  const scheduleTimerDoneNotification = useCallback(
    async (targetEndsAt: number) => {
      if (!isRnWebViewAvailable()) return;

      const rawSeconds = Math.ceil((targetEndsAt - Date.now()) / 1000);
      if (rawSeconds <= 0) return;

      const seconds = Math.max(1, rawSeconds);

      try {
        const result = await rnRequest(
          "MISSION_TIMER_NOTIFICATION_SCHEDULE_REQUEST",
          {
            userId: currentUser?.id,
            username: currentUser?.username,
            notificationKey,
            seconds,
            targetTimeMs: targetEndsAt,
            title: `${label} 타이머 완료`,
            body: `${label} 타이머가 끝났어요. 앱으로 돌아와 완료 버튼을 눌러보세요.`,
            data: {
              notificationKey,
              type: "mission_timer_done",
              endsAt: targetEndsAt,
            },
          },
        );

        if (!result?.scheduled) {
          console.warn(
            "타이머 완료 알림 예약 실패:",
            result?.reason || "unknown",
          );
        } else {
          console.log("타이머 완료 알림 예약 성공:", {
            notificationKey,
            identifier: result.identifier,
            seconds,
            targetTimeMs: targetEndsAt,
            endsAt: targetEndsAt,
          });
        }
      } catch (error) {
        console.warn("타이머 완료 알림 예약 실패:", error);
      }
    },
    [
      currentUser?.id,
      currentUser?.username,
      isRnWebViewAvailable,
      label,
      notificationKey,
      rnRequest,
    ],
  );

  const cancelTimerDoneNotification = useCallback(async () => {
    if (!isRnWebViewAvailable()) return;

    try {
      await rnRequest("MISSION_TIMER_NOTIFICATION_CANCEL_REQUEST", {
        userId: currentUser?.id,
        username: currentUser?.username,
        notificationKey,
      });
    } catch (error) {
      console.warn("타이머 완료 알림 취소 실패:", error);
    }
  }, [
    currentUser?.id,
    currentUser?.username,
    isRnWebViewAvailable,
    notificationKey,
    rnRequest,
  ]);


  useEffect(() => {
    if (state !== "running") return;

    const id = window.setInterval(() => {
      if (!endsAt) return;

      const remain = Math.max(0, Math.ceil((endsAt - Date.now()) / 1000));
      setSecondsLeft(remain);

      if (remain <= 0) {
        setState("done");
      }
    }, 1000);

    return () => window.clearInterval(id);
  }, [state, endsAt]);

  useEffect(() => {
    if (state === "done" && !completeCalledRef.current) {
      completeCalledRef.current = true;
      hadRunningStateRef.current = false;

      // 알림은 이미 RN 예약 알림이 담당한다.
      // 여기서 NOW_REQUEST를 보내면 AI 미션 페이지 안에서 알림이 2번 온다.
      onComplete();
    }
  }, [state, onComplete]);

  useEffect(() => {
    if (state === "running" && endsAt && endsAt > Date.now()) {
      if (scheduledEndsAtRef.current !== endsAt) {
        scheduledEndsAtRef.current = endsAt;
        void scheduleTimerDoneNotification(endsAt);
      }
      return;
    }

    // 중요:
    // 페이지 이동/재진입 과정에서 state가 잠깐 idle로 잡힐 수 있다.
    // 이때 예약 알림을 취소하면, 다른 페이지나 앱 밖에서 알림이 오지 않는다.
    // 따라서 idle 상태라고 자동 취소하지 않는다.
  }, [state, endsAt, scheduleTimerDoneNotification]);

  const fmt = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m.toString().padStart(2, "0")}:${sec
      .toString()
      .padStart(2, "0")}`;
  };

  const totalSeconds = Math.max(minutes * 60, 1);
  const progress = 1 - secondsLeft / totalSeconds;

  if (state === "idle") {
    return (
      <motion.button
        whileTap={{ scale: 0.95 }}
        onClick={() => {
          const now = Date.now();
          const nextEndsAt = now + minutes * 60 * 1000;

          setSecondsLeft(minutes * 60);
          setState("running");
          completeCalledRef.current = false;
          hadRunningStateRef.current = true;

          onStart({
            startedAt: now,
            endsAt: nextEndsAt,
            uiState: "running",
          });

          scheduledEndsAtRef.current = nextEndsAt;
          void scheduleTimerDoneNotification(nextEndsAt);
        }}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-500/20 border border-violet-400/30 text-violet-300 text-[11px] font-semibold"
      >
        <Play className="w-3 h-3" />
        {label} 시작
      </motion.button>
    );
  }

  if (state === "running") {
    return (
      <div className="flex items-center gap-2 mt-1">
        <Timer className="w-3.5 h-3.5 text-violet-400 animate-pulse" />
        <span className="text-xs font-mono text-violet-300">
          {fmt(secondsLeft)}
        </span>
        <div className="flex-1 h-1.5 bg-white/10 rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-gradient-to-r from-violet-500 to-purple-500 rounded-full"
            style={{ width: `${progress * 100}%` }}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-500/20 border border-emerald-400/30 text-emerald-300 text-[11px] font-semibold">
      <CheckCircle2 className="w-3 h-3" />
      완료됨
    </div>
  );
};

export default MissionTimerWidget;