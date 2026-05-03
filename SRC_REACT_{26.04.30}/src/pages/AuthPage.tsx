/**
 * 🔐 인증 페이지 컴포넌트 (백엔드 통합)
 * 
 *  * RN WebView 브릿지를 통한 백엔드 인증 처리
 */

import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { Eye, EyeOff, Mail, Lock, User, ArrowRight, Bell, AlertCircle, Sparkles, ChevronUp, Calendar, FileText, Image as ImageIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import { useAppStore } from '@/stores/appStore';
import { useRnBridge, parseJwtPayload, AUTO_LOGIN_KEY } from '@/hooks/useRnBridge';
import { toast } from 'sonner';
import { z } from 'zod';
import Logo from "@/assets/logo.png";

type AuthMode = 'login' | 'signup';
type ForgotStep = 'email' | 'reset';


const emailSchema = z.string().trim()
  .min(1, { message: '이메일을 입력해주세요' })
  .includes('@', { message: '이메일에 @를 포함해야 합니다' })
  .refine((email) => email.endsWith('.com'), { message: '이메일은 .com으로 끝나야 합니다' })
  .refine((email) => {
    const parts = email.split('@');
    return parts.length === 2 && parts[0].length > 0 && parts[1].length > 4;
  }, { message: '올바른 이메일 형식을 입력해주세요' });
const passwordSchema = z.string().min(6, { message: '비밀번호는 6자 이상이어야 합니다' });
const nameSchema = z.string().trim().min(2, { message: '이름은 2자 이상이어야 합니다' }).max(20, { message: '이름은 20자 이하여야 합니다' });

interface FormErrors {
  name?: string;
  email?: string;
  password?: string;
  confirmPassword?: string;
  birthDate?: string;
}

const calculateAge = (birthDate: string): number => {
  const today = new Date();
  const birth = new Date(birthDate);
  let age = today.getFullYear() - birth.getFullYear();
  const monthDiff = today.getMonth() - birth.getMonth();
  if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birth.getDate())) age--;
  return age;
};

const isOldEnough = (birthDate: string): boolean => calculateAge(birthDate) >= 14;

const AuthPage = () => {
  const navigate = useNavigate();
  const { login, setPermissions, setOnboardingComplete, setInBodyData, setManualData } = useAppStore();
  const { rnRequest } = useRnBridge();
  
  const [mode, setMode] = useState<AuthMode>('login');
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(() => localStorage.getItem(AUTO_LOGIN_KEY) === 'true');
  const [isLoading, setIsLoading] = useState(false);
  const [showPermissions, setShowPermissions] = useState(false);
  const [showAuthPanel, setShowAuthPanel] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [birthDate, setBirthDate] = useState('');
  const [errors, setErrors] = useState<FormErrors>({});
  const [termsAgreed, setTermsAgreed] = useState(false);
  const [showTermsDialog, setShowTermsDialog] = useState(false);
  const [notificationsEnabled, setNotificationsEnabled] = useState(false);
  const [imagePermissionEnabled, setImagePermissionEnabled] = useState(false);
  const [showForgotPassword, setShowForgotPassword] = useState(false);
  const [forgotStep, setForgotStep] = useState<ForgotStep>('email');
  const [forgotEmail, setForgotEmail] = useState('');
  const [forgotEmailError, setForgotEmailError] = useState('');
  const [forgotNewPassword, setForgotNewPassword] = useState('');
  const [forgotConfirmPassword, setForgotConfirmPassword] = useState('');
  const [forgotPasswordErrors, setForgotPasswordErrors] = useState<{ newPassword?: string; confirmPassword?: string }>({});
  const [forgotLoading, setForgotLoading] = useState(false);
  const [showForgotNewPassword, setShowForgotNewPassword] = useState(false);


  // 이메일 중복 체크 캐시 (백엔드용)
  const [emailCheckCache, setEmailCheckCache] = useState<{ email: string; exists: boolean } | null>(null);
  
  const checkEmailExistsCached = (value: string) => {
    if (emailCheckCache && emailCheckCache.email === value) {
      return emailCheckCache.exists;
    }
    return false;
  };

  useEffect(() => {
    const autoLoginEnabled = localStorage.getItem(AUTO_LOGIN_KEY) === 'true';
    if (!autoLoginEnabled) {
      localStorage.removeItem("access_token");
      localStorage.removeItem("token_type");
      localStorage.removeItem("auth_token");
    }
  }, []);

  // 백엔드 이메일 중복 체크 (회원가입 모드에서만)
  useEffect(() => {
    if (mode !== 'signup') return;
    const emailResult = emailSchema.safeParse(email);
    if (!emailResult.success) { setEmailCheckCache(null); return; }
    
    let cancelled = false;
    (async () => {
      try {
        const data = await rnRequest("AUTH_CHECK_USERNAME_REQUEST", { username: email });
        if (!cancelled) setEmailCheckCache({ email, exists: !!data.exists });
      } catch {
        if (!cancelled) setEmailCheckCache(null);
      }
    })();
    return () => { cancelled = true; };
  }, [email, mode, rnRequest]);

  const validateForm = (): boolean => {
    const newErrors: FormErrors = {};
    const emailResult = emailSchema.safeParse(email);
    if (!emailResult.success) newErrors.email = emailResult.error.errors[0].message;
    const passwordResult = passwordSchema.safeParse(password);
    if (!passwordResult.success) newErrors.password = passwordResult.error.errors[0].message;
    
    if (mode === 'signup') {
      const nameResult = nameSchema.safeParse(fullName);
      if (!nameResult.success) newErrors.name = nameResult.error.errors[0].message;
      if (!birthDate) newErrors.birthDate = '생년월일을 입력해주세요';
      else if (!isOldEnough(birthDate)) newErrors.birthDate = '만 14세 이상만 가입할 수 있습니다';
      if (checkEmailExistsCached(email)) newErrors.email = '이미 등록된 이메일입니다';
      if (password !== confirmPassword) newErrors.confirmPassword = '비밀번호가 일치하지 않습니다';
    }
    
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validateForm()) { toast.error('입력 정보를 확인해주세요'); return; }
    if (mode === 'signup') {
      setTermsAgreed(false);
      setNotificationsEnabled(false);
      setImagePermissionEnabled(false);
      setShowTermsDialog(false);
      setShowPermissions(true);
      return;
    }
    await performLogin();
  };

  const handleNotificationCheckboxChange = async (checked: boolean) => {
    if (!checked) {
      setNotificationsEnabled(false);
      setPermissions({ gps: false, notifications: false });
      return;
    }

    try {
      const result = await rnRequest("AUTH_NOTIFICATION_PERMISSION_REQUEST", {});
      const granted = !!result?.granted;
      setNotificationsEnabled(granted);
      setPermissions({ gps: false, notifications: granted });

      if (!granted) {
        toast.error("알림 권한이 허용되지 않았습니다.");
      }
    } catch (e: any) {
      setNotificationsEnabled(false);
      setPermissions({ gps: false, notifications: false });
      toast.error(e?.message ? String(e.message) : "알림 권한 요청에 실패했습니다.");
    }
  };

  const handleImagePermissionCheckboxChange = async (checked: boolean) => {
    if (!checked) {
      setImagePermissionEnabled(false);
      setPermissions({ image: false });
      return;
    }

    try {
      const result = await rnRequest("AUTH_IMAGE_PERMISSION_REQUEST", {
        openSettingsIfDenied: true,
      });
      const granted = !!result?.granted;
      setImagePermissionEnabled(granted);
      setPermissions({ image: granted });

      if (!granted) {
        toast.error("사진 / 이미지 권한이 허용되지 않았습니다.");
      }
    } catch (e: any) {
      setImagePermissionEnabled(false);
      setPermissions({ image: false });
      toast.error(e?.message ? String(e.message) : "사진 / 이미지 권한 요청에 실패했습니다.");
    }
  };

  const handlePermissionsComplete = async () => {
    if (!termsAgreed) { toast.error('이용약관에 동의해주세요'); return; }
    await performSignup();
  };

  const performLogin = async () => {
    setIsLoading(true);

    try {
      const data = await rnRequest("AUTH_LOGIN_REQUEST", {
        username: email,
        password,
      });

      const accessToken = data?.access_token;

      if (!accessToken) {
        throw new Error("로그인 토큰을 받지 못했습니다.");
      }

      localStorage.setItem("access_token", accessToken);
      localStorage.setItem("auth_token", accessToken);
      localStorage.setItem("token_type", data?.token_type || "bearer");
      localStorage.setItem(AUTO_LOGIN_KEY, rememberMe ? "true" : "false");

      const jwtPayload = parseJwtPayload(accessToken);
      const userId = jwtPayload?.user_id ? String(jwtPayload.user_id) : "0";

      const userForStore = {
        id: String(data?.user_id ?? userId),
        username: email,
        nickname: data?.nickname ?? (email.includes("@") ? email.split("@")[0] : email),
        birthDate: data?.birth_date ?? undefined,
        createdAt: data?.created_at ?? new Date(),
        profileImage: data?.profile_image_data_url ?? undefined,
        imagePermissionGranted: !!data?.image_permission_granted,
        imagePermissionStatus: data?.image_permission_status ?? null,
      };

      login(userForStore, rememberMe, accessToken);
      toast.success("로그인 성공!");

      try {
        // 1) 먼저 기존 최신 데이터 조회
        let latest = await rnRequest("HEALTHCARE_LATEST_FAST_REQUEST", {
          token: accessToken,
        });

        
        // 2) 기존 데이터가 "HealthConnect 연동 상태"일 때만 자동 동기화 실행
        if (latest?.inbody) {
          const existingSource = String(latest.inbody.source || "").toLowerCase();
          const existingGender = latest.inbody.gender || "male";
          const existingGoal = latest.inbody.goal || "건강 유지";

          if (existingSource === "healthconnect") {
            try {
              await rnRequest("HC_SYNC_AND_SAVE_REQUEST", {
                token: accessToken,
                gender: existingGender,
                goal: existingGoal,
                userId: userForStore.id,
                username: userForStore.username,
              });

              // 자동 동기화 후 최신 데이터 다시 조회
              latest = await rnRequest("HEALTHCARE_LATEST_FAST_REQUEST", {
                token: accessToken,
              });
            } catch (syncErr) {
              console.warn("로그인 직후 자동 Health Sync 실패:", syncErr);
            }
          }
        }

        // 3) 최신 데이터 반영
        if (latest?.inbody) {
          const r = latest.inbody;

          if ((r.source || "").toLowerCase() === "manual") {
            setManualData({
              name: r.name || userForStore.nickname || "사용자",
              age: typeof r.age === "number" ? r.age : 25,
              gender: r.gender || "male",
              height: Number(r.height || 0),
              weight: Number(r.weight || 0),
              body_fat: Number(r.body_fat || 0),
              muscle_mass: Number(r.muscle_mass || 0),
              goal: r.goal || "건강 유지",
            });
          } else if ((r.source || "").toLowerCase() === "healthconnect") {
            setInBodyData({
              id: String(r.id ?? "latest"),
              userId: String(r.user_id ?? userForStore.id),
              syncedAt: r.updated_at ? new Date(r.updated_at) : new Date(),
              name: r.name || userForStore.nickname || "사용자",
              age: typeof r.age === "number" ? r.age : 25,
              gender: r.gender || "male",
              height: Number(r.height || 0),
              weight: Number(r.weight || 0),
              body_fat: Number(r.body_fat || 0),
              muscle_mass: Number(r.muscle_mass || 0),
              goal: r.goal || "건강 유지",
              bmi: Number(r.bmi || 0),
              bmr: Number(r.bmr || 0),
            } as any);
          } else {
            setManualData({
              name: r.name || userForStore.nickname || "사용자",
              age:
                typeof r.age === "number"
                  ? r.age
                  : userForStore.birthDate
                    ? calculateAge(userForStore.birthDate)
                    : 25,
              gender: r.gender || "male",
              height: Number(r.height || 0),
              weight: Number(r.weight || 0),
              body_fat: Number(r.body_fat || 0),
              muscle_mass: Number(r.muscle_mass || 0),
              goal: r.goal || "건강 유지",
            });
          }

          setOnboardingComplete(true);
          navigate("/inbody");
          return;
        }

        // 기존 데이터가 없으면 자동 동기화도 안 하고 온보딩으로
        setOnboardingComplete(false);
        navigate("/onboarding");
      } catch (err) {
        console.warn("HEALTHCARE_LATEST_FAST_REQUEST failed:", err);
        setOnboardingComplete(false);
        navigate("/onboarding");
      }
    } catch (e: any) {
      toast.error(e?.message ? String(e.message) : "로그인에 실패했습니다.");
    } finally {
      setIsLoading(false);
    }
  };

  const performSignup = async () => {
    setIsLoading(true);

    try {
      await rnRequest("AUTH_SIGNUP_REQUEST", {
        username: email,
        password,
        name: fullName,
        birth_date: birthDate,
        image_permission_granted: imagePermissionEnabled,
        image_permission_status: imagePermissionEnabled ? "granted" : "undetermined",
      });

      toast.success("회원가입 완료! 로그인해주세요.");

      setMode("login");
      setPassword("");
      setFullName('');
      setConfirmPassword("");
      setBirthDate("");
      setErrors({});
      setTermsAgreed(false);
      setNotificationsEnabled(false);
      setImagePermissionEnabled(false);
      setShowTermsDialog(false);
      setShowPermissions(false);
    } catch (e: any) {
      toast.error(e?.message ? String(e.message) : "회원가입에 실패했습니다.");
    } finally {
      setIsLoading(false);
    }
  };

  const clearError = (field: keyof FormErrors) => {
    setErrors(prev => ({ ...prev, [field]: undefined }));
  };

  const handleForgotEmailCheck = async () => {
    setForgotEmailError('');
    const emailResult = emailSchema.safeParse(forgotEmail);
    if (!emailResult.success) {
      setForgotEmailError(emailResult.error.errors[0].message);
      return;
    }
    setForgotLoading(true);
    try {
      const data = await rnRequest("AUTH_CHECK_USERNAME_REQUEST", { username: forgotEmail });
      if (data?.exists) {
        setForgotStep('reset');
        setForgotEmailError('');
      } else {
        setForgotEmailError('아이디가 존재하지 않습니다');
      }
    } catch {
      setForgotEmailError('확인 중 오류가 발생했습니다. 다시 시도해주세요.');
    } finally {
      setForgotLoading(false);
    }
  };
  const handleForgotPasswordSubmit = async () => {
    const newErrors: { newPassword?: string; confirmPassword?: string } = {};
    const pwResult = passwordSchema.safeParse(forgotNewPassword);
    if (!pwResult.success) newErrors.newPassword = pwResult.error.errors[0].message;
    if (forgotNewPassword !== forgotConfirmPassword) newErrors.confirmPassword = '비밀번호가 일치하지 않습니다';
    setForgotPasswordErrors(newErrors);
    if (Object.keys(newErrors).length > 0) return;
    setForgotLoading(true);
    try {
      await rnRequest("AUTH_RESET_PASSWORD_REQUEST", { username: forgotEmail, new_password: forgotNewPassword });
      toast.success('비밀번호가 재설정되었습니다. 로그인해주세요.');
      closeForgotPassword();
    } catch (e: any) {
      toast.error(e?.message ? String(e.message) : '비밀번호 재설정에 실패했습니다.');
    } finally {
      setForgotLoading(false);
    }
  };
  const closeForgotPassword = () => {
    setShowForgotPassword(false);
    setForgotStep('email');
    setForgotEmail('');
    setForgotEmailError('');
    setForgotNewPassword('');
    setForgotConfirmPassword('');
    setForgotPasswordErrors({});
    setShowForgotNewPassword(false);
  };



  const ErrorMessage = ({ message }: { message?: string }) => {
    if (!message) return null;
    return (
      <motion.div initial={{ opacity: 0, y: -5 }} animate={{ opacity: 1, y: 0 }} className="flex items-center gap-1.5 mt-1.5 text-destructive">
        <AlertCircle className="w-3.5 h-3.5" />
        <span className="text-xs">{message}</span>
      </motion.div>
    );
  };

  return (
    <div className="h-full bg-background flex flex-col overflow-hidden relative">
      {/* 풀스크린 배경 */}
      <div className="absolute inset-0 gradient-primary">
        <motion.div animate={{ y: [0, -20, 0], rotate: [0, 5, 0] }} transition={{ duration: 6, repeat: Infinity, ease: "easeInOut" }} className="absolute top-20 right-8 w-32 h-32 rounded-full bg-white/10 blur-2xl" />
        <motion.div animate={{ y: [0, 15, 0], scale: [1, 1.1, 1] }} transition={{ duration: 5, repeat: Infinity, ease: "easeInOut", delay: 0.5 }} className="absolute top-40 left-6 w-24 h-24 rounded-full bg-accent/20 blur-xl" />
        <motion.div animate={{ y: [0, -10, 0] }} transition={{ duration: 4, repeat: Infinity, ease: "easeInOut", delay: 1 }} className="absolute bottom-60 right-10 w-20 h-20 rounded-full bg-white/15 blur-lg" />
        <motion.div animate={{ opacity: [0.3, 0.8, 0.3], scale: [1, 1.3, 1] }} transition={{ duration: 2, repeat: Infinity }} className="absolute top-32 right-16">
          <Sparkles className="w-8 h-8 text-white/40" />
        </motion.div>
        <motion.div animate={{ opacity: [0.5, 1, 0.5] }} transition={{ duration: 2.5, repeat: Infinity, delay: 0.3 }} className="absolute top-56 left-12">
          <Sparkles className="w-5 h-5 text-white/30" />
        </motion.div>
        <motion.div animate={{ opacity: [0.4, 0.9, 0.4] }} transition={{ duration: 3, repeat: Infinity, delay: 0.8 }} className="absolute top-72 right-24">
          <Sparkles className="w-6 h-6 text-accent/50" />
        </motion.div>
      </div>

      {/* 메인 콘텐츠 */}
      <div className="relative flex-1 flex flex-col items-center justify-center px-8">
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }} className="text-center">
          <motion.div initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ type: "spring", stiffness: 200, damping: 15, delay: 0.3 }} className="w-40 h-40 flex items-center justify-center mx-auto mb-6">
            <motion.img src={Logo} alt="logo" className="w-36 h-36 object-contain drop-shadow-2xl" animate={{ rotate: [0, 3, -3, 0] }} transition={{ duration: 2, repeat: Infinity }} />
          </motion.div>
          <motion.h1 initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.5 }} className="text-5xl font-black text-white tracking-tight mb-3">
            <span className="bg-gradient-to-r from-blue-200 via-purple-300 to-pink-300 bg-clip-text text-transparent drop-shadow-lg">업!</span> 바디
          </motion.h1>
          <motion.p initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.6 }} className="text-white/80 text-lg">
            게임과 함께 레벨업하는 나의 몸
          </motion.p>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.8 }} className="absolute bottom-32 left-0 right-0 px-8">
          <Button onClick={() => setShowAuthPanel(true)} className="w-full h-16 rounded-2xl text-lg font-bold bg-white text-primary hover:bg-white/90 transition-all shadow-2xl">
            <motion.span animate={{ y: [0, -2, 0] }} transition={{ duration: 1.5, repeat: Infinity }} className="flex items-center gap-2">
              시작하기 <ChevronUp className="w-5 h-5" />
            </motion.span>
          </Button>
          <p className="text-center text-white/60 text-sm mt-4">
            계정이 있으신가요? <button onClick={() => { setShowAuthPanel(true); setMode('login'); }} className="text-white underline">로그인</button>
          </p>
        </motion.div>
      </div>

      {/* 슬라이드업 인증 패널 */}
      <AnimatePresence>
        {showAuthPanel && (
          <>
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => !showPermissions && setShowAuthPanel(false)} className="absolute inset-0 bg-black/40 z-10" />
            <motion.div layout initial={{ y: "100%" }} animate={{ y: 0 }} exit={{ y: "100%" }} transition={{ type: "spring", damping: 30, stiffness: 300, layout: { duration: 0.35, ease: "easeInOut" } }} className="absolute bottom-0 left-0 right-0 bg-card rounded-t-3xl z-20 max-h-[85%] overflow-y-auto">
              <div className="flex justify-center pt-3 pb-2"><div className="w-12 h-1.5 bg-muted-foreground/30 rounded-full" /></div>
              <motion.div className="px-6 pb-[calc(env(safe-area-inset-bottom)+2rem)] overflow-hidden" layout transition={{ type: "spring", damping: 25, stiffness: 200 }}>
                <AnimatePresence mode="wait" initial={false}>
                  {!showPermissions ? (
                    <motion.div key={`auth-form-${mode}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
                      <div className="text-center mb-6">
                        <h2 className="text-2xl font-bold text-foreground">{mode === 'login' ? '만나서 반가워요!' : '함께 시작해볼까요?'}</h2>
                        <p className="text-muted-foreground mt-1 text-sm">{mode === 'login' ? '계정에 로그인하세요' : '새 계정을 만들어보세요'}</p>
                      </div>
                      <div className="flex bg-secondary rounded-xl p-1 mb-6">
                        <button className={`flex-1 py-3 rounded-lg text-sm font-medium transition-all ${mode === 'login' ? 'bg-card text-foreground card-shadow' : 'text-muted-foreground'}`} onClick={() => { if (mode !== 'login') { setMode('login'); setEmail(''); setPassword(''); setFullName(''); setConfirmPassword(''); setBirthDate(''); setErrors({}); } }}>로그인</button>
                        <button className={`flex-1 py-3 rounded-lg text-sm font-medium transition-all ${mode === 'signup' ? 'bg-card text-foreground card-shadow' : 'text-muted-foreground'}`} onClick={() => { if (mode !== 'signup') { setMode('signup'); setEmail(''); setPassword(''); setFullName(''); setConfirmPassword(''); setBirthDate(''); setErrors({}); } }}>회원가입</button>
                      </div>
                      <form onSubmit={handleSubmit} className="space-y-4">
                        {mode === 'signup' && (
                          <>
                            <div className="space-y-1.5">
                              <Label htmlFor="name" className="text-sm text-muted-foreground">이름</Label>
                              <div className="relative">
                                <User className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
                                <Input id="name" type="text" placeholder="이름을 입력하세요" value={fullName} onChange={(e) => { setFullName(e.target.value); clearError('name'); }} className={`pl-12 h-14 rounded-xl border-border bg-secondary/50 focus:bg-card transition-colors ${errors.name ? 'border-destructive focus-visible:ring-destructive' : ''}`} />
                              </div>
                              <ErrorMessage message={errors.name} />
                            </div>
                            <div className="space-y-1.5">
                              <Label htmlFor="birthDate" className="text-sm text-muted-foreground">생년월일</Label>
                              <div className="relative">
                                <Calendar className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
                                <Input id="birthDate" type="date" value={birthDate} onChange={(e) => { setBirthDate(e.target.value); clearError('birthDate'); }} max={new Date().toISOString().split('T')[0]} className={`pl-12 h-14 rounded-xl border-border bg-secondary/50 focus:bg-card transition-colors ${errors.birthDate ? 'border-destructive focus-visible:ring-destructive' : ''}`} />
                              </div>
                              <ErrorMessage message={errors.birthDate} />
                              <p className="text-xs text-muted-foreground">만 14세 이상만 가입 가능합니다</p>
                            </div>
                          </>
                        )}
                        <div className="space-y-1.5">
                          <Label htmlFor="email" className="text-sm text-muted-foreground">이메일</Label>
                          <div className="relative">
                            <Mail className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
                            <Input id="email" type="email" placeholder="example@email.com" value={email} onChange={(e) => { setEmail(e.target.value); clearError('email'); }} className={`pl-12 h-14 rounded-xl border-border bg-secondary/50 focus:bg-card transition-colors ${errors.email ? 'border-destructive focus-visible:ring-destructive' : ''}`} />
                          </div>
                          <ErrorMessage message={errors.email} />
                        </div>
                        <div className="space-y-1.5">
                          <Label htmlFor="password" className="text-sm text-muted-foreground">비밀번호</Label>
                          <div className="relative">
                            <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
                            <Input id="password" type={showPassword ? 'text' : 'password'} placeholder="비밀번호를 입력하세요" value={password} onChange={(e) => { setPassword(e.target.value); clearError('password'); }} className={`pl-12 pr-12 h-14 rounded-xl border-border bg-secondary/50 focus:bg-card transition-colors ${errors.password ? 'border-destructive focus-visible:ring-destructive' : ''}`} />
                            <button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute right-4 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors">
                              {showPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                            </button>
                          </div>
                          <ErrorMessage message={errors.password} />
                          {mode === 'signup' && !errors.password && <p className="text-xs text-muted-foreground mt-1">6자 이상 입력해주세요</p>}
                        </div>
                        {mode === 'signup' && (
                          <div className="space-y-1.5">
                            <Label htmlFor="confirmPassword" className="text-sm text-muted-foreground">비밀번호 확인</Label>
                            <div className="relative">
                              <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
                              <Input id="confirmPassword" type="password" placeholder="비밀번호를 다시 입력하세요" value={confirmPassword} onChange={(e) => { setConfirmPassword(e.target.value); clearError('confirmPassword'); }} className={`pl-12 h-14 rounded-xl border-border bg-secondary/50 focus:bg-card transition-colors ${errors.confirmPassword ? 'border-destructive focus-visible:ring-destructive' : ''}`} />
                            </div>
                            <ErrorMessage message={errors.confirmPassword} />
                          </div>
                        )}
                        {mode === 'login' && (
                          <div className="flex items-center justify-between">
                            <div className="flex items-center space-x-2">
                              <Checkbox id="remember" checked={rememberMe} onCheckedChange={(checked) => setRememberMe(checked as boolean)} />
                              <Label htmlFor="remember" className="text-sm text-muted-foreground cursor-pointer">자동로그인</Label>
                            </div>
                            <button
                              type="button"
                              onClick={() => {
                                setForgotEmail(email);
                                setForgotEmailError('');
                                setShowForgotPassword(true);
                              }}
                              className="text-sm text-primary hover:underline"
                            >
                              비밀번호 찾기
                            </button>
                          </div>
                        )}
                        <Button type="submit" disabled={isLoading} className="w-full h-14 rounded-xl text-base font-semibold gradient-primary text-primary-foreground hover:opacity-90 transition-opacity mt-2">
                          {isLoading ? <div className="w-6 h-6 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin" /> : <>{mode === 'login' ? '로그인' : '다음'}<ArrowRight className="w-5 h-5 ml-2" /></>}
                        </Button>
                      </form>
                    </motion.div>
                  ) : (
                    <motion.div key="permissions" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }} className="space-y-6">
                      <div className="text-center mb-6">
                        <h2 className="text-2xl font-bold text-foreground">앱 권한 설정</h2>
                        <p className="text-muted-foreground mt-2">더 나은 서비스를 위해 권한을 설정해주세요</p>
                      </div>
                      <div className="space-y-4">
                        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="bg-secondary/50 rounded-2xl p-5 flex items-center justify-between">
                          <div className="flex items-center gap-4">
                            <div className="w-12 h-12 rounded-xl gradient-primary flex items-center justify-center"><FileText className="w-6 h-6 text-primary-foreground" /></div>
                            <div><h3 className="font-semibold text-foreground">이용약관</h3><p className="text-sm text-muted-foreground">서비스 이용약관 동의</p></div>
                          </div>
                          <Checkbox checked={termsAgreed} onCheckedChange={(checked) => { if (checked) setShowTermsDialog(true); else setTermsAgreed(false); }} className="w-6 h-6" />
                        </motion.div>
                        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }} className="bg-secondary/50 rounded-2xl p-5 flex items-center justify-between">
                          <div className="flex items-center gap-4">
                            <div className="w-12 h-12 rounded-xl gradient-warm flex items-center justify-center"><Bell className="w-6 h-6 text-primary-foreground" /></div>
                            <div><h3 className="font-semibold text-foreground">알림</h3><p className="text-sm text-muted-foreground">미션 및 챌린지 알림</p></div>
                          </div>
                          <Checkbox checked={notificationsEnabled} onCheckedChange={(checked) => handleNotificationCheckboxChange(checked as boolean)} className="w-6 h-6" />
                        </motion.div>
                        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }} className="bg-secondary/50 rounded-2xl p-5 flex items-center justify-between">
                          <div className="flex items-center gap-4">
                            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-pink-500 to-amber-400 flex items-center justify-center"><ImageIcon className="w-6 h-6 text-white" /></div>
                            <div><h3 className="font-semibold text-foreground">사진 / 이미지</h3><p className="text-sm text-muted-foreground">프로필 사진 및 인증 이미지 업로드</p></div>
                          </div>
                          <Checkbox checked={imagePermissionEnabled} onCheckedChange={(checked) => handleImagePermissionCheckboxChange(checked as boolean)} className="w-6 h-6" />
                        </motion.div>
                      </div>
                      <div className="pt-4 space-y-3">
                        <Button onClick={handlePermissionsComplete} disabled={isLoading} className="w-full h-14 rounded-xl text-base font-semibold gradient-primary text-primary-foreground hover:opacity-90 transition-opacity">
                          {isLoading ? <div className="w-6 h-6 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin" /> : <>완료<ArrowRight className="w-5 h-5 ml-2" /></>}
                        </Button>
                        <button type="button" onClick={() => setShowPermissions(false)} className="w-full py-3 text-muted-foreground hover:text-foreground transition-colors">이전으로</button>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            </motion.div>
          </>
        )}
      </AnimatePresence>

      {/* 이용약관 동의 팝업 */}
      <Dialog open={showTermsDialog} onOpenChange={() => {}}>
        <DialogContent className="max-w-[90%] max-h-[80vh] rounded-2xl p-0 [&>button]:hidden" onPointerDownOutside={(e) => e.preventDefault()} onEscapeKeyDown={(e) => e.preventDefault()}>
          <DialogHeader className="px-6 pt-6 pb-2">
            <DialogTitle className="text-lg font-bold">업! 바디 이용약관</DialogTitle>
            <DialogDescription className="text-sm text-muted-foreground">아래 이용약관을 읽고 동의해주세요</DialogDescription>
          </DialogHeader>
          <ScrollArea className="px-6 max-h-[50vh]">
            <div className="text-sm text-foreground/80 space-y-4 pb-4 leading-relaxed">
              <p className="text-xs text-muted-foreground">(졸업작품용)</p>
              <div><h4 className="font-semibold text-foreground mb-1">제1조 (목적)</h4><p>본 약관은 "업! 바디" 에서 제공하는 게임화된 운동 챌린지 서비스의 이용과 관련하여 이용자의 권리, 의무 및 책임사항을 규정함을 목적으로 합니다.</p><p className="mt-1">본 프로젝트는 소프트웨어학과 졸업작품 연구 목적으로 제작된 시스템입니다.</p></div>
              <div><h4 className="font-semibold text-foreground mb-1">제2조 (서비스 개요)</h4><p>본 프로젝트는 다음과 같은 기능을 제공합니다.</p><ul className="list-disc pl-4 mt-1 space-y-0.5"><li>InBody API를 통한 사용자 신체 데이터 연동</li><li>신체 데이터(키, 체중, BMI 등) 분석 및 평균 건강 수치 비교</li><li>GPT 기반 맞춤형 운동 챌린지 생성</li><li>챌린지 성공 여부 판별 시스템</li><li>게임화 요소 제공 (경험치, 캐릭터 성장, 업적 메달)</li><li>지속적인 목표 달성 시스템</li></ul></div>
              <div><h4 className="font-semibold text-foreground mb-1">제3조 (서비스의 연구 목적)</h4><p>본 프로젝트는 개인 맞춤형 건강 챌린지 생성 시스템 연구, 게임화(Gamification) 기반 행동 유도 모델 검증, 인공지능(GPT) 기반 헬스케어 미션 생성 연구 목적으로 개발되었습니다.</p></div>
              <div><h4 className="font-semibold text-foreground mb-1">제4조 (의료 서비스 아님)</h4><p>본 프로젝트에서 제공되는 모든 데이터 분석 및 GPT 생성 미션은 의료 진단, 치료 목적의 운동 처방, 건강 상태 개선 보장을 포함하지 않습니다.</p></div>
              <div><h4 className="font-semibold text-foreground mb-1">제5조 (데이터 수집 및 활용)</h4><p>프로젝트는 서비스 제공을 위해 InBody 연동 신체 데이터, 활동 수행 결과 데이터, 챌린지 수행 기록, 시스템 이용 로그를 활용할 수 있습니다.</p></div>
              <div><h4 className="font-semibold text-foreground mb-1">제6조 (인공지능 기반 기능)</h4><p>프로젝트는 OpenAI API를 활용하여 사용자 신체 데이터를 기반으로 운동 챌린지를 생성합니다.</p></div>
              <div><h4 className="font-semibold text-foreground mb-1">제7조 (게임화 요소)</h4><p>프로젝트는 캐릭터 성장 시스템, 경험치 및 업적 보상, 챌린지 성공 기반 레벨업 등의 게임화 요소를 포함합니다.</p></div>
              <div><h4 className="font-semibold text-foreground mb-1">제8조 (책임의 제한)</h4><p>프로젝트는 GPT 생성 미션 수행 중 발생할 수 있는 신체적 영향에 대해 책임을 지지 않습니다.</p></div>
              <div><h4 className="font-semibold text-foreground mb-1">제9조 (서비스 특성)</h4><p>본 프로젝트는 졸업작품용 연구 시스템으로, 서비스의 안정성 및 지속적 제공이 보장되지 않을 수 있습니다.</p></div>
              <div><h4 className="font-semibold text-foreground mb-1">제10조 (약관 변경)</h4><p>연구 진행 과정에 따라 약관이 변경될 수 있으며, 변경 시 안내됩니다.</p></div>
            </div>
          </ScrollArea>
          <div className="px-6 pb-6 pt-2">
            <Button onClick={() => { setTermsAgreed(true); setShowTermsDialog(false); }} className="w-full h-12 rounded-xl font-semibold gradient-primary text-primary-foreground">동의합니다</Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* 비밀번호 찾기 팝업 */}
      <Dialog open={showForgotPassword} onOpenChange={() => {}}>
        <DialogContent className="max-w-[90%] rounded-2xl p-0 [&>button]:hidden" onPointerDownOutside={(e) => e.preventDefault()} onEscapeKeyDown={(e) => e.preventDefault()}>
          <AnimatePresence mode="wait">
            {forgotStep === 'email' ? (
              <motion.div key="forgot-email" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="p-6 space-y-5">
                <div className="text-center">
                  <h2 className="text-xl font-bold text-foreground">비밀번호 찾기</h2>
                  <p className="text-sm text-muted-foreground mt-1">가입한 이메일(아이디)을 입력해주세요</p>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="forgot-email" className="text-sm text-muted-foreground">이메일</Label>
                  <div className="relative">
                    <Mail className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
                    <Input
                      id="forgot-email"
                      type="email"
                      placeholder="example@email.com"
                      value={forgotEmail}
                      onChange={(e) => { setForgotEmail(e.target.value); setForgotEmailError(''); }}
                      className={`pl-12 h-14 rounded-xl border-border bg-secondary/50 focus:bg-card transition-colors ${forgotEmailError ? 'border-destructive focus-visible:ring-destructive' : ''}`}
                    />
                  </div>
                  <ErrorMessage message={forgotEmailError} />
                </div>
                <div className="flex gap-3 pt-2">
                  <Button type="button" variant="outline" onClick={closeForgotPassword} className="flex-1 h-12 rounded-xl font-semibold">취소</Button>
                  <Button type="button" onClick={handleForgotEmailCheck} disabled={forgotLoading} className="flex-1 h-12 rounded-xl font-semibold gradient-primary text-primary-foreground">
                    {forgotLoading ? <div className="w-5 h-5 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin" /> : '다음'}
                  </Button>
                </div>
              </motion.div>
            ) : (
              <motion.div key="forgot-reset" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="p-6 space-y-5">
                <div className="text-center">
                  <h2 className="text-xl font-bold text-foreground">비밀번호 재설정</h2>
                  <p className="text-sm text-muted-foreground mt-1">새로운 비밀번호를 입력해주세요</p>
                </div>
                <div className="space-y-4">
                  <div className="space-y-1.5">
                    <Label htmlFor="forgot-new-password" className="text-sm text-muted-foreground">새 비밀번호</Label>
                    <div className="relative">
                      <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
                      <Input
                        id="forgot-new-password"
                        type={showForgotNewPassword ? 'text' : 'password'}
                        placeholder="새 비밀번호 (6자 이상)"
                        value={forgotNewPassword}
                        onChange={(e) => { setForgotNewPassword(e.target.value); setForgotPasswordErrors(prev => ({ ...prev, newPassword: undefined })); }}
                        className={`pl-12 pr-12 h-14 rounded-xl border-border bg-secondary/50 focus:bg-card transition-colors ${forgotPasswordErrors.newPassword ? 'border-destructive focus-visible:ring-destructive' : ''}`}
                      />
                      <button type="button" onClick={() => setShowForgotNewPassword(!showForgotNewPassword)} className="absolute right-4 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors">
                        {showForgotNewPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                      </button>
                    </div>
                    <ErrorMessage message={forgotPasswordErrors.newPassword} />
                    {!forgotPasswordErrors.newPassword && <p className="text-xs text-muted-foreground">6자 이상 입력해주세요</p>}
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="forgot-confirm-password" className="text-sm text-muted-foreground">비밀번호 확인</Label>
                    <div className="relative">
                      <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-muted-foreground" />
                      <Input
                        id="forgot-confirm-password"
                        type="password"
                        placeholder="비밀번호를 다시 입력하세요"
                        value={forgotConfirmPassword}
                        onChange={(e) => { setForgotConfirmPassword(e.target.value); setForgotPasswordErrors(prev => ({ ...prev, confirmPassword: undefined })); }}
                        className={`pl-12 h-14 rounded-xl border-border bg-secondary/50 focus:bg-card transition-colors ${forgotPasswordErrors.confirmPassword ? 'border-destructive focus-visible:ring-destructive' : ''}`}
                      />
                    </div>
                    <ErrorMessage message={forgotPasswordErrors.confirmPassword} />
                  </div>
                </div>
                <div className="flex gap-3 pt-2">
                  <Button type="button" variant="outline" onClick={closeForgotPassword} className="flex-1 h-12 rounded-xl font-semibold">취소</Button>
                  <Button type="button" onClick={handleForgotPasswordSubmit} disabled={forgotLoading} className="flex-1 h-12 rounded-xl font-semibold gradient-primary text-primary-foreground">
                    {forgotLoading ? <div className="w-5 h-5 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin" /> : '완료'}
                  </Button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default AuthPage;
