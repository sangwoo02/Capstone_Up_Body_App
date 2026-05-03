/**
 * 📋 온보딩 페이지 (백엔드 통합)
 * 
 * Samsung Health 연동 시 rnRequest를 통해 백엔드와 통신.
 * 직접 입력 시에도 백엔드에 데이터 저장.
 */

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { Keyboard, ArrowRight, RefreshCw, AlertCircle, CheckCircle, X, Heart } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAppStore } from "@/stores/appStore";
import { useRnBridge } from "@/hooks/useRnBridge";
import { toast } from "sonner";
import type { InBodyData, ManualInputData } from "@/types";

type InputMethod = "select" | "samsung_health" | "samsung_health_sync" | "manual";

const MIN_HEIGHT_CM = 50;
const MAX_HEIGHT_CM = 250;
const MIN_WEIGHT_KG = 10;
const MAX_WEIGHT_KG = 200;

const GOAL_OPTIONS = [
  { value: "건강 유지", label: "건강 유지" },
  { value: "체중 감량", label: "체중 감량" },
];

const calculateAge = (birthDate: string): number => {
  const today = new Date();
  const birth = new Date(birthDate);
  let age = today.getFullYear() - birth.getFullYear();
  const monthDiff = today.getMonth() - birth.getMonth();
  if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birth.getDate())) age--;
  return age;
};

const clampNumberString = (value: string, min: number, max: number) => {
  if (!value.trim()) return "";
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) return "";
  return String(Math.min(max, Math.max(min, parsed)));
};

const OnboardingPage = () => {
  const navigate = useNavigate();
  const { setInBodyData, setManualData, setOnboardingComplete, user, resetHealthcareLinkedData } = useAppStore();
  const { rnRequest } = useRnBridge();

  const [method, setMethod] = useState<InputMethod>("select");
  const [isLoading, setIsLoading] = useState(false);
  const [syncError, setSyncError] = useState(false);
  const [syncSuccess, setSyncSuccess] = useState(false);
  const [syncComplete, setSyncComplete] = useState(false);

  const [shGender, setShGender] = useState<"male" | "female">("male");
  const [shGoal, setShGoal] = useState("건강 유지");
  const [height, setHeight] = useState("");
  const [weight, setWeight] = useState("");
  const [gender, setGender] = useState<"male" | "female">("male");
  const [bodyFat, setBodyFat] = useState("");
  const [muscleMass, setMuscleMass] = useState("");
  const [goal, setGoal] = useState("건강 유지");

  const handleSamsungHealthNext = () => setMethod("samsung_health_sync");

  const handleSamsungHealthSync = async () => {
    setIsLoading(true);
    setSyncError(false);
    setSyncSuccess(false);
    setSyncComplete(false);

    try {
      const token = localStorage.getItem("access_token");

      const data = await rnRequest("HC_SYNC_AND_SAVE_REQUEST", {
        token: token || undefined,
        gender: shGender,
        goal: shGoal,
        force_history_days: 30,
        userId: user?.id,
        username: user?.username,
      });
      setSyncSuccess(true);

      setTimeout(async () => {
        setSyncComplete(true);

        const age = user?.birthDate ? calculateAge(user.birthDate) : 25;
        const heightMeters = data?.hc?.height?.meters ?? null;
        const weightKg = data?.hc?.weight?.kg ?? null;
        const heightCm = typeof heightMeters === "number" ? heightMeters * 100 : 175;
        const weightVal = typeof weightKg === "number" ? weightKg : 70.5;
        const heightM = heightCm / 100;
        const bmi = heightM > 0 ? +(weightVal / (heightM * heightM)).toFixed(1) : 23.0;
        const bmr = shGender === "male"
          ? Math.round(10 * weightVal + 6.25 * heightCm - 5 * age + 5)
          : Math.round(10 * weightVal + 6.25 * heightCm - 5 * age - 161);

        const inBodyData: InBodyData = {
          id: String(data?.saved?.inbody_id ?? "0"),
          userId: user?.id || "0",
          syncedAt: new Date(),
          name: user?.nickname || "사용자",
          age,
          gender: shGender,
          height: +heightCm.toFixed(1),
          weight: +weightVal.toFixed(1),
          body_fat: 18.5,
          muscle_mass: 0,
          goal: shGoal,
          bmi,
          bmr,
        };

        setInBodyData(inBodyData);
        toast.success("Health Connect 데이터 동기화 및 저장 완료!");
        setTimeout(() => {
          setOnboardingComplete(true);
          navigate("/inbody");
        }, 1200);
      }, 800);
    } catch (e: any) {
      setSyncError(true);
      toast.error(e?.message ? String(e.message) : "Health Connect 동기화에 실패했습니다.");
    } finally {
      setIsLoading(false);
    }
  };


  const handleManualSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!height || !weight) {
      toast.error("키와 몸무게를 입력해주세요.");
      return;
    }

    const parsedHeight = Number.parseFloat(height);
    const parsedWeight = Number.parseFloat(weight);

    if (!Number.isFinite(parsedHeight) || !Number.isFinite(parsedWeight)) {
      toast.error("키와 몸무게는 숫자로 입력해주세요.");
      return;
    }

    if (parsedHeight < MIN_HEIGHT_CM || parsedHeight > MAX_HEIGHT_CM) {
      toast.error(`키는 ${MIN_HEIGHT_CM}~${MAX_HEIGHT_CM}cm 범위로 입력해주세요.`);
      return;
    }

    if (parsedWeight < MIN_WEIGHT_KG || parsedWeight > MAX_WEIGHT_KG) {
      toast.error(`몸무게는 ${MIN_WEIGHT_KG}~${MAX_WEIGHT_KG}kg 범위로 입력해주세요.`);
      return;
    }

    setIsLoading(true);

    const token = localStorage.getItem("access_token");
    const age = user?.birthDate ? calculateAge(user.birthDate) : 25;

    try {
      await rnRequest("INBODY_MANUAL_SAVE_REQUEST", {
        token: token || undefined,
        height: parsedHeight,
        weight: parsedWeight,
        gender,
        goal,
      });

      const manualData: ManualInputData = {
        name: user?.nickname || "사용자",
        height: parsedHeight,
        weight: parsedWeight,
        age,
        gender,
        body_fat: bodyFat ? parseFloat(bodyFat) : gender === "male" ? 20 : 25,
        muscle_mass: muscleMass ? parseFloat(muscleMass) : gender === "male" ? 30 : 22,
        goal,
      };

      setManualData(manualData);
      setOnboardingComplete(true);
      toast.success("신체 정보가 저장되었습니다!");
      navigate("/inbody");
    } catch (e: any) {
      toast.error(e?.message ? String(e.message) : "신체 정보 저장에 실패했습니다.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSkip = () => {
    resetHealthcareLinkedData();
    setOnboardingComplete(true);
    navigate("/inbody");
  };

  return (
    <div className="min-h-screen bg-background flex flex-col">
      <div className="gradient-primary px-5 pt-[calc(env(safe-area-inset-top)+1.3rem)] pb-8">
        <motion.div initial={{ opacity: 0, y: -20 }} animate={{ opacity: 1, y: 0 }} className="text-primary-foreground">
          <h1 className="text-2xl font-bold">신체 정보 입력</h1>
          <p className="text-primary-foreground/80 mt-2">맞춤형 건강 미션을 위해 정보를 입력해주세요</p>
        </motion.div>
      </div>

      <div className="flex-1 px-6 py-8">
        <AnimatePresence mode="wait">
          {method === "select" && (
            <motion.div key="select" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -20 }} className="space-y-4">
              <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }} onClick={() => setMethod("samsung_health")} className="w-full bg-card rounded-2xl p-6 card-shadow flex items-center gap-4 text-left">
                <div className="w-14 h-14 rounded-xl bg-gradient-to-br from-red-500 to-orange-500 flex items-center justify-center flex-shrink-0 shadow-sm"><Heart className="w-7 h-7 text-white" /></div>
                <div className="flex-1"><h3 className="font-semibold text-lg text-foreground">Samsung Health 앱 연동</h3><p className="text-muted-foreground text-sm mt-1">Samsung Health 앱 연동으로 신체 정보 분석 비교 및 활동 히스토리와 AI 미션 챌린지를 한 번에 생성할 수 있습니다.</p></div>
                <ArrowRight className="w-5 h-5 text-muted-foreground" />
              </motion.button>
              <motion.button whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }} onClick={() => setMethod("manual")} className="w-full bg-card rounded-2xl p-6 card-shadow flex items-center gap-4 text-left">
                <div className="w-14 h-14 rounded-xl bg-secondary flex items-center justify-center flex-shrink-0"><Keyboard className="w-7 h-7 text-secondary-foreground" /></div>
                <div className="flex-1"><h3 className="font-semibold text-lg text-foreground">직접 입력</h3><p className="text-muted-foreground text-sm mt-1">키, 몸무게 등 기본 정보를 직접 입력합니다. AI 미션 챌린지를 생성할 수 없습니다.</p></div>
                <ArrowRight className="w-5 h-5 text-muted-foreground" />
              </motion.button>
              <div className="pt-4"><button onClick={handleSkip} className="w-full py-4 text-muted-foreground hover:text-foreground transition-colors text-sm">나중에 입력할게요 →</button></div>
            </motion.div>
          )}

          {method === "samsung_health" && (
            <motion.div key="samsung_health" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }}>
              <div className="space-y-5">
                <div className="bg-card rounded-2xl p-6 card-shadow text-center mb-6">
                  <div className="w-20 h-20 mx-auto rounded-2xl bg-gradient-to-br from-red-500 to-orange-500 flex items-center justify-center mb-4 shadow-md"><Heart className="w-10 h-10 text-white" /></div>
                  <h3 className="text-xl font-bold text-foreground">Samsung Health 연동</h3>
                  <p className="text-muted-foreground mt-2 text-sm">연동을 위해 기본 정보를 입력해주세요</p>
                </div>
                <div className="space-y-2">
                  <Label className="text-sm text-muted-foreground">성별</Label>
                  <div className="grid grid-cols-2 gap-3">
                    <button type="button" onClick={() => setShGender("male")} className={`h-14 rounded-xl font-semibold transition-all ${shGender === "male" ? "gradient-primary text-primary-foreground" : "bg-secondary text-secondary-foreground"}`}>남성</button>
                    <button type="button" onClick={() => setShGender("female")} className={`h-14 rounded-xl font-semibold transition-all ${shGender === "female" ? "gradient-primary text-primary-foreground" : "bg-secondary text-secondary-foreground"}`}>여성</button>
                  </div>
                </div>
                <div className="space-y-2">
                  <Label className="text-sm text-muted-foreground">목표</Label>
                  <div className="grid grid-cols-2 gap-2">
                    {GOAL_OPTIONS.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        onClick={() => setShGoal(option.value)}
                        className={`h-12 rounded-xl text-sm font-medium transition-all ${
                          shGoal === option.value
                            ? "gradient-primary text-primary-foreground"
                            : "bg-secondary text-secondary-foreground"
                        }`}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="pt-4 space-y-3">
                  <Button onClick={handleSamsungHealthNext} className="w-full h-14 rounded-xl text-base font-semibold gradient-primary text-primary-foreground">연동하기</Button>
                  <button type="button" onClick={() => setMethod("select")} className="w-full py-3 text-muted-foreground hover:text-foreground transition-colors">이전으로</button>
                </div>
              </div>
            </motion.div>
          )}

          {method === "samsung_health_sync" && (
            <motion.div key="samsung_health_sync" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} className="space-y-6">
              <div className="bg-card rounded-2xl p-6 card-shadow text-center">
                {!syncSuccess ? (
                  <>
                    <motion.div className="w-20 h-20 mx-auto rounded-2xl bg-gradient-to-br from-red-500 to-orange-500 flex items-center justify-center mb-6 shadow-md" animate={isLoading ? { boxShadow: ["0 0 0 0 rgba(59,130,246,0)", "0 0 0 20px rgba(59,130,246,0.2)", "0 0 0 0 rgba(59,130,246,0)"] } : {}} transition={{ duration: 1.5, repeat: Infinity }}>
                      {isLoading ? <RefreshCw className="w-10 h-10 text-white animate-spin" /> : <Heart className="w-10 h-10 text-white" />}
                    </motion.div>
                    <h3 className="text-xl font-bold text-foreground">{isLoading ? "연동중..." : "Samsung Health 연동"}</h3>
                    <p className="text-muted-foreground mt-2">{isLoading ? "데이터를 가져오고 있습니다. 잠시만 기다려주세요." : "Samsung Health 앱에 로그인되어 있는지 확인해주세요. 또한 Android 13 버전 이상 혹은 Health Connect 앱이 설치되어있어야 합니다."}</p>
                    {isLoading && <motion.div className="mt-6 flex justify-center gap-2" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>{[0, 1, 2].map(i => <motion.div key={i} className="w-3 h-3 rounded-full bg-primary" animate={{ y: [0, -10, 0], opacity: [0.3, 1, 0.3] }} transition={{ duration: 0.8, repeat: Infinity, delay: i * 0.2 }} />)}</motion.div>}
                  </>
                ) : !syncComplete ? (
                  <>
                    <motion.div className="w-20 h-20 mx-auto rounded-full bg-success/10 flex items-center justify-center mb-6" initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ type: "spring", stiffness: 200, damping: 15 }}>
                      <motion.div initial={{ scale: 0, rotate: -45 }} animate={{ scale: 1, rotate: 0 }} transition={{ delay: 0.2, type: "spring", stiffness: 200 }}><CheckCircle className="w-12 h-12 text-success" /></motion.div>
                    </motion.div>
                    <motion.h3 className="text-xl font-bold text-foreground" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }}>연동 완료!</motion.h3>
                    <motion.p className="text-muted-foreground mt-2" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.4 }}>데이터를 저장하고 있습니다...</motion.p>
                  </>
                ) : (
                  <>
                    <motion.div className="w-20 h-20 mx-auto rounded-full bg-success/10 flex items-center justify-center mb-6" animate={{ boxShadow: ["0 0 0 0 rgba(34,197,94,0.4)", "0 0 0 20px rgba(34,197,94,0)"] }} transition={{ duration: 1.5, repeat: Infinity }}>
                      <CheckCircle className="w-12 h-12 text-success" />
                    </motion.div>
                    <h3 className="text-xl font-bold text-foreground">동기화 완료!</h3>
                    <p className="text-muted-foreground mt-2">메인 화면으로 이동합니다...</p>
                  </>
                )}
              </div>
              {!syncSuccess && !isLoading && (
                <div className="rounded-xl overflow-hidden border border-border">
                  {/* 빨간색 경고 영역 */}
                  <div className="bg-red-500/10 border-b border-red-500/20 p-4">
                    <div className="flex items-start gap-2.5">
                      <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
                      <p className="text-xs text-red-500 leading-relaxed">
                        Health Connect 네트워크로 인한 오류 실패 시, <p>Samsung Health 앱에서 키와 몸무게를 임의로 수정하시고 다시 연동을 시도해보세요.</p>
                      </p>
                    </div>
                  </div>

                  {/* 노란색 안내 영역 */}
                  <div className="bg-amber-500/10 p-4 space-y-3">
                    <div className="flex items-start gap-2.5">
                      <AlertCircle className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        이전에 직접 입력한 신체 정보(키, 몸무게, 성별 등)가 있는 경우, Health Connect 연동 시 해당 데이터는 삭제되고 연동된 데이터로 대체됩니다. 기존 입력 내용이 사라질 수 있으니 유의하세요.
                      </p>
                    </div>

                    <div className="flex items-start gap-2.5">
                      <AlertCircle className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        연동이 완료되면 신체 정보는 Health Connect 데이터를 기반으로 자동 관리됩니다. 이후에는 직접 입력 기능이 비활성화되며, 수동으로 수정하실 수 없습니다.
                      </p>
                    </div>
                  </div>
                </div>
              )}
              <AnimatePresence>
                {syncError && (
                  <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="bg-destructive/10 border border-destructive/20 rounded-xl p-3 flex items-start gap-3">
                    <AlertCircle className="w-5 h-5 text-destructive flex-shrink-0 mt-0.5" />
                    <div className="flex-1"><h4 className="font-semibold text-destructive text-sm">동기화 오류</h4><p className="text-destructive/80 text-xs mt-0.5">네트워크 연결을 확인하고 다시 시도해주세요.</p></div>
                    <button onClick={() => setSyncError(false)} className="text-destructive/60 hover:text-destructive"><X className="w-4 h-4" /></button>
                  </motion.div>
                )}
              </AnimatePresence>
              {!syncSuccess && (
                <div className="space-y-3">
                  <Button onClick={handleSamsungHealthSync} disabled={isLoading} className="w-full h-14 rounded-xl text-base font-semibold gradient-primary text-primary-foreground">
                    {isLoading ? "연동중..." : syncError ? "다시 시도" : "연동 시작"}
                  </Button>
                  <button type="button" onClick={() => setMethod("samsung_health")} className="w-full py-3 text-muted-foreground hover:text-foreground transition-colors">이전으로</button>
                </div>
              )}
            </motion.div>
          )}

          {method === "manual" && (
            <motion.div key="manual" initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }}>
              <form onSubmit={handleManualSubmit} className="space-y-5">
                <div className="space-y-2">
                  <Label>키 (cm)</Label>
                  <Input
                    type="number"
                    value={height}
                    min={MIN_HEIGHT_CM}
                    max={MAX_HEIGHT_CM}
                    step="0.1"
                    inputMode="decimal"
                    onChange={e => setHeight(e.target.value)}
                    onBlur={() => setHeight(prev => clampNumberString(prev, MIN_HEIGHT_CM, MAX_HEIGHT_CM))}
                    className="h-14 rounded-xl bg-secondary/50 text-center text-lg font-semibold"
                    required
                  />
                  <p className="text-xs text-muted-foreground">50~250cm 범위로 입력해주세요.</p>
                </div>
                <div className="space-y-2">
                  <Label>몸무게 (kg)</Label>
                  <Input
                    type="number"
                    value={weight}
                    min={MIN_WEIGHT_KG}
                    max={MAX_WEIGHT_KG}
                    step="0.1"
                    inputMode="decimal"
                    onChange={e => setWeight(e.target.value)}
                    onBlur={() => setWeight(prev => clampNumberString(prev, MIN_WEIGHT_KG, MAX_WEIGHT_KG))}
                    className="h-14 rounded-xl bg-secondary/50 text-center text-lg font-semibold"
                    required
                  />
                  <p className="text-xs text-muted-foreground">10~200kg 범위로 입력해주세요.</p>
                </div>
                <div className="space-y-2">
                  <Label className="text-sm text-muted-foreground">성별</Label>
                  <div className="grid grid-cols-2 gap-3">
                    <button type="button" onClick={() => setGender("male")} className={`h-14 rounded-xl font-semibold transition-all ${gender === "male" ? "gradient-primary text-primary-foreground" : "bg-secondary text-secondary-foreground"}`}>남성</button>
                    <button type="button" onClick={() => setGender("female")} className={`h-14 rounded-xl font-semibold transition-all ${gender === "female" ? "gradient-primary text-primary-foreground" : "bg-secondary text-secondary-foreground"}`}>여성</button>
                  </div>
                </div>
                <div className="space-y-2">
                  <Label className="text-sm text-muted-foreground">목표</Label>
                  <div className="grid grid-cols-2 gap-2">
                    {GOAL_OPTIONS.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        onClick={() => setGoal(option.value)}
                        className={`h-12 rounded-xl text-sm font-medium transition-all ${
                          goal === option.value
                            ? "gradient-primary text-primary-foreground"
                            : "bg-secondary text-secondary-foreground"
                        }`}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="pt-4 space-y-3">
                  <Button type="submit" disabled={isLoading} className="w-full h-14 rounded-xl text-base font-semibold gradient-primary text-primary-foreground">
                    {isLoading ? "저장 중..." : "저장하기"}
                  </Button>
                  <button type="button" onClick={() => setMethod("select")} className="w-full py-3 text-muted-foreground hover:text-foreground transition-colors">이전으로</button>
                </div>
              </form>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
};

export default OnboardingPage;
