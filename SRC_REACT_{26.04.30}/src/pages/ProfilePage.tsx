/**
 * 👤 프로필 설정 페이지 (백엔드 통합)
 * 
 * rnRequest를 통해 비밀번호 변경, 회원탈퇴, 연동 해제, 로그아웃 등을 백엔드에 요청.
 */

import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { User, RefreshCw, Keyboard, Lock, LogOut, ChevronRight, AlertCircle, X, UserX, AlertTriangle, Unlink } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useRnBridge } from '@/hooks/useRnBridge';
import { useAppStore } from '@/stores/appStore';
import { toast } from 'sonner';
import { profileApi } from '@/services/api';
import type { InBodyData } from '@/types';
import AppLayout from '@/components/AppLayout';

type ModalType = 'password' | 'deleteAccount' | 'unlinkSamsung' | 'logout' | null;
type BodyDataStatus = 'none' | 'partial' | 'synced';

const calculateAge = (birthDate: string): number => {
  const today = new Date();
  const birth = new Date(birthDate);
  let age = today.getFullYear() - birth.getFullYear();
  const monthDiff = today.getMonth() - birth.getMonth();
  if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birth.getDate())) age--;
  return age;
};

const ProfilePage = () => {
  const navigate = useNavigate();
  const {
    user,
    logout,
    deleteAccount,
    inBodyData,
    setInBodyData,
    hasInBodyData,
    hasInBodySynced,
    hasMissionsGenerated,
    resetHealthcareLinkedData,
  } = useAppStore();
  const { rnRequest } = useRnBridge();
  const userAge = user?.birthDate ? calculateAge(user.birthDate) : null;

  const [activeModal, setActiveModal] = useState<ModalType>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [profileAvatarUrl, setProfileAvatarUrl] = useState<string | null>(user?.profileImage || null);
  const [syncError, setSyncError] = useState(false);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [deleteConfirmText, setDeleteConfirmText] = useState('');
  const [unlinkConfirmText, setUnlinkConfirmText] = useState('');
  const [passwordErrors, setPasswordErrors] = useState<{ currentPassword?: string; newPassword?: string; confirmPassword?: string }>({});

  useEffect(() => {
    let cancelled = false;

    const loadProfileHeader = async () => {
      const token = localStorage.getItem("access_token") || localStorage.getItem("auth_token");
      if (!token) return;

      try {
        const details = await profileApi.getDetails();
        if (cancelled) return;

        setProfileAvatarUrl(details.profile.profile_image_data_url || null);
      } catch {
        if (!cancelled) setProfileAvatarUrl(null);
      }
    };

    loadProfileHeader();

    return () => {
      cancelled = true;
    };
  }, []);

  const getBodyDataStatus = (): BodyDataStatus => {
    if (!hasInBodyData) return 'none';
    if (hasInBodySynced) return 'synced';
    return 'partial';
  };
  const bodyDataStatus = getBodyDataStatus();
  const canGenerateMissions = bodyDataStatus === 'synced';

  const handleInBodyResync = async () => {
    setIsLoading(true);
    setSyncError(false);

    try {
      const token = localStorage.getItem("access_token");
      if (!token) {
        throw new Error("로그인이 필요합니다.");
      }

      await rnRequest("HC_SYNC_AND_SAVE_REQUEST", {
        token,
        gender: inBodyData?.gender || "male",
        goal: inBodyData?.goal || "건강 유지",
        force_history_days: 30,
        fallback_height_cm: inBodyData?.height,
        fallback_weight_kg: inBodyData?.weight,
        userId: user?.id,
        username: user?.username,
      });

      const latest = await rnRequest("HEALTHCARE_LATEST_FAST_REQUEST", { token });

      if (latest?.inbody) {
        const r = latest.inbody;
        const updated: InBodyData = {
          id: String(r.id),
          userId: String(r.user_id),
          syncedAt: new Date(),
          name: r.name || user?.nickname || "사용자",
          age: r.age ?? (userAge ?? 25),
          gender: r.gender || "male",
          height: Number(r.height || 0),
          weight: Number(r.weight || 0),
          body_fat: Number(r.body_fat || 0),
          muscle_mass: Number(r.muscle_mass || 0),
          goal: r.goal || "건강 유지",
          bmi: Number(r.bmi || 0),
          bmr: Number(r.bmr || 0),
        };
        setInBodyData(updated);
        toast.success("Samsung Health 데이터가 갱신되었습니다!");
      } else {
        throw new Error("최신 신체 데이터를 가져오지 못했습니다.");
      }
    } catch (e: any) {
      setSyncError(true);
      toast.error(e?.message ? String(e.message) : "Samsung Health 데이터 갱신에 실패했습니다.");
    } finally {
      setIsLoading(false);
    }
  };

  const handlePasswordChange = async (e: React.FormEvent) => {
    e.preventDefault();

    const errors: typeof passwordErrors = {};
    if (!currentPassword.trim()) errors.currentPassword = '현재 비밀번호를 입력해주세요.';
    if (newPassword.length < 6) errors.newPassword = '비밀번호는 6자 이상이어야 합니다.';
    if (currentPassword === newPassword && newPassword.length > 0) {
      errors.newPassword = '현재 비밀번호와 동일한 비밀번호입니다.';
    }
    if (newPassword !== confirmPassword) {
      errors.confirmPassword = '새 비밀번호가 일치하지 않습니다.';
    }

    setPasswordErrors(errors);
    if (Object.keys(errors).length > 0) return;

    setIsLoading(true);

    try {
      const token = localStorage.getItem("access_token");
      if (!token) {
        throw new Error("로그인이 필요합니다.");
      }

      await rnRequest("AUTH_CHANGE_PASSWORD_REQUEST", {
        token,
        currentPassword,
        newPassword,
      });

      toast.success("비밀번호가 변경되었습니다.");
      setActiveModal(null);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setPasswordErrors({});
    } catch (e: any) {
      const message = e?.message ? String(e.message) : "비밀번호 변경에 실패했습니다.";

      if (message.includes("현재 비밀번호가 일치하지 않습니다")) {
        setPasswordErrors({ currentPassword: "현재 비밀번호가 일치하지 않습니다." });
      } else if (message.includes("6자 이상")) {
        setPasswordErrors({ newPassword: "비밀번호는 6자 이상이어야 합니다." });
      } else {
        toast.error(message);
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleDeleteAccount = async () => {
    if (deleteConfirmText !== '회원탈퇴') {
      toast.error("'회원탈퇴'를 정확히 입력해주세요.");
      return;
    }

    setIsLoading(true);

    try {
      const token = localStorage.getItem("access_token");
      if (!token) {
        throw new Error("로그인이 필요합니다.");
      }

      await rnRequest("AUTH_DELETE_ACCOUNT_REQUEST", { token });

      deleteAccount();
      toast.success("회원탈퇴가 완료되었습니다.");
      navigate("/");
    } catch (e: any) {
      toast.error(e?.message ? String(e.message) : "회원탈퇴에 실패했습니다.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleUnlinkSamsung = async () => {
    if (unlinkConfirmText !== '해제') {
      toast.error("'해제'를 정확히 입력해주세요.");
      return;
    }

    setIsLoading(true);

    try {
      const token = localStorage.getItem("access_token");
      if (!token) {
        throw new Error("로그인이 필요합니다.");
      }

      await rnRequest("HEALTHCARE_UNLINK_REQUEST", { token });

      resetHealthcareLinkedData();
      setActiveModal(null);
      setUnlinkConfirmText('');
      toast.success("Samsung Health 연동이 해제되고 데이터가 삭제되었습니다.");
      navigate("/onboarding");
    } catch (e: any) {
      toast.error(e?.message ? String(e.message) : "연동 해제 및 데이터 삭제에 실패했습니다.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleLogout = async () => {
    setIsLoading(true);

    try {
      const token = localStorage.getItem("access_token");
      if (!token) {
        throw new Error("로그인 정보가 없습니다.");
      }

      await rnRequest("AUTH_LOGOUT_REQUEST", { token });

      logout();
      toast.success("로그아웃되었습니다.");
      navigate("/");
    } catch (e: any) {
      toast.error(e?.message ? String(e.message) : "로그아웃에 실패했습니다.");
    } finally {
      setIsLoading(false);
    }
  };

  const getBodyDataStatusInfo = () => {
    switch (bodyDataStatus) {
      case 'synced': return { text: '연동됨', color: 'text-success', borderColor: 'border-success', bgColor: 'bg-success/10' };
      case 'partial': return { text: '직접 입력됨', color: 'text-warning', borderColor: 'border-warning', bgColor: 'bg-warning/10' };
      default: return { text: '미입력', color: 'text-destructive', borderColor: 'border-destructive', bgColor: 'bg-destructive/10' };
    }
  };
  const getMissionStatusInfo = () => {
    if (canGenerateMissions) return hasMissionsGenerated ? { text: '활성화', color: 'text-success', borderColor: 'border-success' } : { text: '생성 가능', color: 'text-success', borderColor: 'border-success' };
    return { text: '생성 불가', color: 'text-destructive', borderColor: 'border-destructive' };
  };
  const bodyStatusInfo = getBodyDataStatusInfo();
  const missionStatusInfo = getMissionStatusInfo();

  const menuItems = [
    { icon: RefreshCw, label: 'Samsung Health 동기화 갱신', description: hasInBodySynced ? '최신 데이터로 업데이트' : 'Samsung Health 연동 후 사용 가능', action: handleInBodyResync, loading: isLoading && activeModal === null, disabled: !hasInBodySynced },
    { icon: Keyboard, label: '신체 정보 입력', description: hasInBodySynced ? '이미 삼성 헬스로 연동 되었습니다.' : '앱 연동 및 직접 입력', action: () => navigate('/onboarding'), disabled: hasInBodySynced },
    { icon: Lock, label: '비밀번호 변경', description: '계정 보안 설정', action: () => setActiveModal('password') },
  ];

  return (
    <AppLayout>
      <div className="gradient-primary px-6 pt-safe-top pb-8">
        <h1 className="text-xl font-bold text-primary-foreground mb-5 pt-3">프로필 정보</h1>
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="bg-card/10 backdrop-blur-lg rounded-2xl p-4 flex items-center gap-3">
          <div className="w-14 h-14 rounded-full bg-primary-foreground flex items-center justify-center shrink-0 overflow-hidden">
            {profileAvatarUrl ? (
              <img src={profileAvatarUrl} alt="프로필" className="w-full h-full object-cover" />
            ) : (
              <User className="w-7 h-7 text-primary" />
            )}
          </div>
          <div className="flex-1 min-w-0 text-primary-foreground">
            <div className="flex items-center gap-2"><h2 className="text-lg font-bold truncate">{user?.nickname || '사용자'}</h2>{userAge && <span className="text-sm text-primary-foreground/70 bg-primary-foreground/20 px-2 py-0.5 rounded-full shrink-0">만 {userAge}세</span>}</div>
            <p className="text-primary-foreground/70 text-sm truncate">{user?.username}</p>
          </div>
          <button
            onClick={() => navigate('/profile/details')}
            className="shrink-0 flex items-center gap-1 bg-primary-foreground/15 hover:bg-primary-foreground/25 active:bg-primary-foreground/30 backdrop-blur text-primary-foreground text-xs font-semibold px-3 py-2 rounded-xl border border-primary-foreground/20 transition-colors"
          >
            프로필 설정
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </motion.div>
      </div>
      <div className="px-6 -mt-4">
        <div className="grid grid-cols-2 gap-3">
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className={`bg-card rounded-xl p-3 card-shadow border-l-4 ${bodyStatusInfo.borderColor}`}><p className="text-xs text-muted-foreground">신체 데이터</p><p className={`font-semibold mt-0.5 text-sm ${bodyStatusInfo.color}`}>{bodyStatusInfo.text}</p></motion.div>
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 }} className={`bg-card rounded-xl p-3 card-shadow border-l-4 ${missionStatusInfo.borderColor}`}><p className="text-xs text-muted-foreground">AI 미션</p><p className={`font-semibold mt-0.5 text-sm ${missionStatusInfo.color}`}>{missionStatusInfo.text}</p></motion.div>
        </div>
      </div>
      <AnimatePresence>{syncError && (<motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} className="mx-6 mt-4 bg-destructive/10 border border-destructive/20 rounded-xl p-3 flex items-start gap-3"><AlertCircle className="w-5 h-5 text-destructive flex-shrink-0 mt-0.5" /><div className="flex-1"><h4 className="font-semibold text-destructive text-sm">동기화 오류</h4><p className="text-destructive/80 text-xs mt-0.5">네트워크 연결을 확인하고 다시 시도해주세요.</p></div><button onClick={() => setSyncError(false)} className="text-destructive/60 hover:text-destructive"><X className="w-4 h-4" /></button></motion.div>)}</AnimatePresence>
      <div className="px-6 py-4 space-y-2">
        {menuItems.map((item, index) => (
          <motion.button key={item.label} initial="rest" animate="rest" whileHover={!item.disabled ? "hover" : undefined} variants={{ rest: { opacity: 1, y: 0 }, hover: { opacity: 1, y: 0 } }} transition={{ delay: 0.2 + index * 0.05 }} onClick={item.action} disabled={item.loading || item.disabled} className={`w-full bg-card rounded-xl p-3.5 card-shadow flex items-center gap-3 text-left ${item.disabled ? 'opacity-50 cursor-not-allowed' : ''}`}>
            <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 ${item.disabled ? 'bg-muted' : 'bg-gradient-to-br from-primary/20 to-info/15'}`}>{item.loading ? <RefreshCw className="w-4 h-4 text-primary animate-spin" /> : <item.icon className={`w-4 h-4 ${item.disabled ? 'text-muted-foreground' : 'text-primary'}`} />}</div>
            <div className="flex-1 min-w-0"><h3 className={`font-medium text-sm ${item.disabled ? 'text-muted-foreground' : 'text-foreground'}`}>{item.label}</h3><p className="text-muted-foreground text-xs mt-0.5 truncate">{item.description}</p></div>
            <ChevronRight className={`w-4 h-4 flex-shrink-0 ${item.disabled ? 'text-muted' : 'text-muted-foreground'}`} />
          </motion.button>
        ))}
      </div>
      {bodyDataStatus === 'synced' && <div className="px-6 pb-4"><motion.button initial={{ opacity: 0 }} animate={{ opacity: 1 }} onClick={() => setActiveModal('unlinkSamsung')} className="w-full flex items-center justify-center gap-2 py-3 text-destructive/70 hover:text-destructive hover:bg-destructive/5 rounded-xl transition-colors text-sm"><Unlink className="w-4 h-4" /><span>Samsung Health 연동 해제 및 데이터 삭제</span></motion.button></div>}
      <div className="px-6 pb-4 space-y-2">
        <button onClick={() => setActiveModal('logout')} className="w-full flex items-center justify-center gap-2 py-3 text-muted-foreground hover:bg-muted rounded-xl transition-colors"><LogOut className="w-5 h-5" /><span className="font-medium">로그아웃</span></button>
        <button onClick={() => setActiveModal('deleteAccount')} className="w-full flex items-center justify-center gap-2 py-2.5 text-destructive/70 hover:text-destructive hover:bg-destructive/5 rounded-xl transition-colors text-sm"><UserX className="w-4 h-4" /><span>회원탈퇴</span></button>
      </div>

      {/* Password Modal */}
      <AnimatePresence>{activeModal === 'password' && (<motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 bg-foreground/50 z-50 flex items-end" onClick={() => setActiveModal(null)}><motion.div initial={{ y: '100%' }} animate={{ y: 0 }} exit={{ y: '100%' }} transition={{ type: 'spring', damping: 25, stiffness: 300 }} onClick={e => e.stopPropagation()} className="w-full max-w-[430px] mx-auto bg-card rounded-t-3xl p-6 safe-area-bottom"><div className="w-12 h-1 bg-muted rounded-full mx-auto mb-6" /><h2 className="text-xl font-bold text-foreground mb-6">비밀번호 변경</h2><form onSubmit={handlePasswordChange} className="space-y-4"><div className="space-y-2"><Label className="text-sm text-muted-foreground">현재 비밀번호</Label><Input type="password" value={currentPassword} onChange={e => { setCurrentPassword(e.target.value); if (passwordErrors.currentPassword) setPasswordErrors(p => ({ ...p, currentPassword: undefined })); }} className={`h-12 rounded-xl ${passwordErrors.currentPassword ? 'border-destructive' : ''}`} required />{passwordErrors.currentPassword && <p className="text-xs text-destructive">{passwordErrors.currentPassword}</p>}</div><div className="space-y-2"><Label className="text-sm text-muted-foreground">새 비밀번호</Label><Input type="password" value={newPassword} onChange={e => { setNewPassword(e.target.value); if (passwordErrors.newPassword) setPasswordErrors(p => ({ ...p, newPassword: undefined })); }} className={`h-12 rounded-xl ${passwordErrors.newPassword ? 'border-destructive' : ''}`} required />{passwordErrors.newPassword && <p className="text-xs text-destructive">{passwordErrors.newPassword}</p>}<p className="text-xs text-muted-foreground">6자 이상 입력해주세요</p></div><div className="space-y-2"><Label className="text-sm text-muted-foreground">새 비밀번호 확인</Label><Input type="password" value={confirmPassword} onChange={e => { setConfirmPassword(e.target.value); if (passwordErrors.confirmPassword) setPasswordErrors(p => ({ ...p, confirmPassword: undefined })); }} className={`h-12 rounded-xl ${passwordErrors.confirmPassword ? 'border-destructive' : ''}`} required />{passwordErrors.confirmPassword && <p className="text-xs text-destructive">{passwordErrors.confirmPassword}</p>}</div><Button type="submit" disabled={isLoading} className="w-full h-12 rounded-xl gradient-primary text-primary-foreground font-semibold mt-4">{isLoading ? '변경 중...' : '비밀번호 변경'}</Button></form></motion.div></motion.div>)}</AnimatePresence>

      {/* Logout Modal */}
      <AnimatePresence>{activeModal === 'logout' && (<motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 bg-foreground/50 z-50 flex items-center justify-center px-6" onClick={() => setActiveModal(null)}><motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.9, opacity: 0 }} onClick={e => e.stopPropagation()} className="w-full max-w-sm bg-card rounded-2xl p-6"><div className="flex items-center justify-center w-16 h-16 mx-auto mb-4 rounded-full bg-muted"><LogOut className="w-8 h-8 text-muted-foreground" /></div><h2 className="text-xl font-bold text-foreground text-center mb-2">로그아웃</h2><p className="text-muted-foreground text-sm text-center mb-6">로그아웃 하시겠습니까?</p><div className="flex gap-3"><Button variant="outline" onClick={() => setActiveModal(null)} disabled={isLoading} className="flex-1 h-12 rounded-xl">취소</Button><Button onClick={handleLogout} disabled={isLoading} className="flex-1 h-12 rounded-xl gradient-primary text-primary-foreground font-semibold">{isLoading ? '처리 중...' : '로그아웃'}</Button></div></motion.div></motion.div>)}</AnimatePresence>


      {/* Delete Account Modal */}
      <AnimatePresence>{activeModal === 'deleteAccount' && (<motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 bg-foreground/50 z-50 flex items-center justify-center px-6" onClick={() => setActiveModal(null)}><motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.9, opacity: 0 }} onClick={e => e.stopPropagation()} className="w-full max-w-sm bg-card rounded-2xl p-6"><div className="flex items-center justify-center w-16 h-16 mx-auto mb-4 rounded-full bg-destructive/10"><AlertTriangle className="w-8 h-8 text-destructive" /></div><h2 className="text-xl font-bold text-foreground text-center mb-2">회원탈퇴</h2><p className="text-muted-foreground text-sm text-center mb-6">탈퇴 시 모든 데이터가 삭제되며 복구할 수 없습니다.<br />계속하시려면 아래에 <span className="font-bold text-destructive">'회원탈퇴'</span>를 입력해주세요.</p><div className="space-y-4"><Input type="text" value={deleteConfirmText} onChange={e => setDeleteConfirmText(e.target.value)} placeholder="회원탈퇴" className="h-12 rounded-xl text-center" /><div className="flex gap-3"><Button variant="outline" onClick={() => { setActiveModal(null); setDeleteConfirmText(''); }} className="flex-1 h-12 rounded-xl">취소</Button><Button onClick={handleDeleteAccount} disabled={isLoading || deleteConfirmText !== '회원탈퇴'} className="flex-1 h-12 rounded-xl bg-destructive hover:bg-destructive/90 text-destructive-foreground">{isLoading ? '처리 중...' : '탈퇴하기'}</Button></div></div></motion.div></motion.div>)}</AnimatePresence>

      {/* Unlink Samsung Health Modal */}
      <AnimatePresence>{activeModal === 'unlinkSamsung' && (<motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="fixed inset-0 bg-foreground/50 z-50 flex items-center justify-center px-6" onClick={() => { setActiveModal(null); setUnlinkConfirmText(''); }}><motion.div initial={{ scale: 0.9, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.9, opacity: 0 }} onClick={e => e.stopPropagation()} className="w-full max-w-sm bg-card rounded-2xl p-6"><div className="flex items-center justify-center w-16 h-16 mx-auto mb-4 rounded-full bg-warning/10"><Unlink className="w-8 h-8 text-warning" /></div><h2 className="text-xl font-bold text-foreground text-center mb-2">연동 해제</h2><div className="text-muted-foreground text-sm text-center mb-6"><p>Samsung Health 연동을 해제하면 모든 신체 데이터와 미션 기록이 영구 삭제됩니다. 게임 데이터는 유지됩니다.</p><p className="mt-1">(활동 히스토리, AI 미션 성공 내역, 나의 기록)</p><p className="mt-4">계속하시려면 아래에 <span className="font-bold text-warning">'해제'</span>를 입력해주세요.</p></div><div className="space-y-4"><Input type="text" value={unlinkConfirmText} onChange={e => setUnlinkConfirmText(e.target.value)} placeholder="해제" className="h-12 rounded-xl text-center" /><div className="flex gap-3"><Button variant="outline" onClick={() => { setActiveModal(null); setUnlinkConfirmText(''); }} className="flex-1 h-12 rounded-xl">취소</Button><Button onClick={handleUnlinkSamsung} disabled={isLoading || unlinkConfirmText !== '해제'} className="flex-1 h-12 rounded-xl bg-warning hover:bg-warning/90 text-warning-foreground">{isLoading ? '처리 중...' : '연동 해제'}</Button></div></div></motion.div></motion.div>)}</AnimatePresence>
    </AppLayout>
  );
};

export default ProfilePage;
