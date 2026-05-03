/**
 * 🗄️ 앱 전역 상태 관리 스토어
 *
 * Zustand를 사용한 전역 상태 관리입니다.
 * localStorage에 persist되어 새로고침 시에도 상태가 유지됩니다.
 *
 * 📦 상태 구조:
 * - Auth: 로그인 상태, 유저 정보, 토큰
 * - Onboarding: 온보딩 완료, 신체 데이터 입력 상태
 * - Data: InBody 데이터, 수동 입력 데이터, 목표 체중, 미션
 * - Game: 캐릭터, 코인, 경험치, 레벨, 배지
 * - Server Game Cache: gameProfile, health 연결 여부, 게임 로딩 상태
 * - Permissions: GPS, 알림 권한
 * - Wearable: 웨어러블 기기 연결 정보
 * - History: 활동 기록, 몸무게 기록
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type {
  User,
  CurrentMission,
  GameProfile,
  InBodyData,
  ManualInputData,
  MissionSlotCode,
} from '@/types';
import { gameApi, healthcareApi, missionsApi } from '@/services/api';

export const AUTO_LOGIN_KEY = 'auto_login_checked';

///////////////////////////////////////0409_코드 추가 작업//////////////////////////////////////
interface OwnedCharacter {
  id: string;
  level: number; // 캐릭터별 독립 레벨
  exp: number;   // 캐릭터별 독립 경험치
}
////////////////////////////////////////////////////////////////////////////////////////////////

interface WearableDevice {
  name: string;
  type: string;
}

interface ActivityRecord {
  date: string; // YYYY-MM-DD
  steps: number;
  calories: number;
}

interface WeightRecord {
  weight: number;
  recordedAt: string; // ISO string
}

const INITIAL_AUTH_STATE = {
  isLoggedIn: false,
  user: null as User | null,
  rememberMe: false,
  authToken: null as string | null,
};

const INITIAL_USER_DATA_STATE = {
  hasCompletedOnboarding: false,
  hasInBodyData: false,
  hasInBodySynced: false,
  hasMissionsGenerated: false,
  inBodyData: null as InBodyData | null,
  manualData: null as ManualInputData | null,
  targetWeight: null as number | null,
  missions: [] as CurrentMission[],
};

const INITIAL_GAME_STATE = {
  hasCreatedCharacter: false,
  selectedCharacter: null as string | null,
  selectedBackground: null as string | null,
  //0409수정
  ownedCharacters: [] as OwnedCharacter[],
  ownedBackgroundIds: [] as string[],
  coins: 0,
  exp: 0,
  level: 1,
  requiredExp: 100,
  equippedBadge: null as string | null,
  missionCoins: 0,
  dailyMissionRegenCount: 0,
  dailyMissionRegenDate: null as string | null,
  missionInteractionState: {} as Record<string, MissionInteractionState>,

  missionUiRequest: {
    refreshingSlot: null as MissionSlotCode | null,
    submittingSlot: null as MissionSlotCode | null,
    actionType: null as 'refresh' | 'retry' | 'complete' | null,
    startedAt: null as number | null,
  },
  // 신프론트 확장 필드
  nickname: null as string | null,
  equippedBadges: [] as string[],
  totalMissionsCompleted: 0,
  totalCoinsEarned: 0,
  completedAchievements: [] as string[],
  pendingAchievements: [] as string[],

  // 레벨업 서버 연동 필드
  canLevelUp: false,
  maxLevel: 10,
  characterStage: 'basic' as string,
};

const INITIAL_SERVER_GAME_STATE = {
  gameProfile: null as GameProfile | null,
  isHealthLinked: false,
  isGameLoading: false,
  hasFetchedGameState: false,
};

const INITIAL_DEVICE_STATE = {
  permissions: {
    gps: false,
    notifications: false,
    image: false,
  },
  wearableDevice: null as WearableDevice | null,
};

const INITIAL_HISTORY_STATE = {
  activityHistory: [] as ActivityRecord[],
  weightHistory: [] as WeightRecord[],
};

interface MissionInteractionState {
  completed: boolean;
  checkinText?: string;
  timerCompleted?: boolean;
  checkedCount?: number;
  routineCompleted?: boolean;

  // 진행 중 상태 유지용
  startedAt?: number;
  endsAt?: number;
  uiState?: "idle" | "running" | "waiting" | "ready" | "done";
  currentRound?: number;
}

interface MissionUiRequestState {
  refreshingSlot: MissionSlotCode | null;
  submittingSlot: MissionSlotCode | null;
  actionType: 'refresh' | 'retry' | 'complete' | 'start' | null;
  startedAt: number | null;
}

interface AppStore {

  // Auth State
  isLoggedIn: boolean;
  user: User | null;
  rememberMe: boolean;
  authToken: string | null;

  // Onboarding State
  hasCompletedOnboarding: boolean;
  hasInBodyData: boolean;
  hasInBodySynced: boolean;
  hasMissionsGenerated: boolean;

  // Data
  inBodyData: InBodyData | null;
  manualData: ManualInputData | null;
  targetWeight: number | null;
  missions: CurrentMission[];

  // Game State
  hasCreatedCharacter: boolean;
  selectedCharacter: string | null;
  selectedBackground: string | null;
  //0409수정
  ownedCharacters: OwnedCharacter[];
  ownedBackgroundIds: string[];
  coins: number;
  exp: number;
  level: number;
  requiredExp: number;
  equippedBadge: string | null;
  missionCoins: number;
  dailyMissionRegenCount: number;
  dailyMissionRegenDate: string | null;

  canLevelUp: boolean;
  maxLevel: number;
  characterStage: string | null;

  nickname: string | null;
  equippedBadges: string[];
  totalMissionsCompleted: number;
  totalCoinsEarned: number;
  completedAchievements: string[];
  pendingAchievements: string[];

  // 서버 기반 게임 상태
  gameProfile: GameProfile | null;
  isHealthLinked: boolean;
  isGameLoading: boolean;
  hasFetchedGameState: boolean;

  // Permissions
  permissions: {
    gps: boolean;
    notifications: boolean;
    image: boolean;
  };

  // Wearable
  wearableDevice: WearableDevice | null;

  // History
  activityHistory: ActivityRecord[];
  weightHistory: WeightRecord[];

  missionInteractionState: Record<string, MissionInteractionState>;
  missionUiRequest: MissionUiRequestState;
  // Simple setters
  setActivityHistory: (records: ActivityRecord[]) => void;
  setWeightHistory: (records: WeightRecord[]) => void;
  setAuthToken: (token: string | null) => void;
  setOnboardingComplete: (complete: boolean) => void;
  setInBodyData: (data: InBodyData | null) => void;
  setManualData: (data: ManualInputData | null) => void;
  setPermissions: (permissions: { gps?: boolean; notifications?: boolean; image?: boolean }) => void;
  setWearableDevice: (device: WearableDevice | null) => void;
  setMissionsGenerated: (generated: boolean) => void;
  setMissions: (missions: CurrentMission[]) => void;
  setTargetWeight: (weight: number | null) => void;
  setCharacter: (characterId: string, backgroundId: string) => void;
  setSelectedBackground: (backgroundId: string) => void;
  setSelectedCharacter: (characterId: string) => void;
  //0409수정
  setOwnedCharacters: (characters: OwnedCharacter[]) => void;
  setOwnedBackgroundIds: (ids: string[]) => void;
  addCoins: (amount: number) => void;
  addExp: (amount: number) => void;
  setEquippedBadge: (badgeId: string | null) => void;
  addActivityRecord: (steps: number, calories: number) => void;
  addWeightRecord: (weight: number) => void;
  addMissionCoins: (amount: number) => void;
  useMissionCoin: () => boolean;
  incrementDailyRegen: () => void;
  getDailyRegenRemaining: () => number;
  setHealthLinked: (linked: boolean) => void;
  syncGameProfile: (profile: GameProfile | null) => void;
  enqueueAchievementCelebration: (achievementCodes: string[]) => void;


  // 신프론트 추가 액션
  setNickname: (name: string | null) => void;
  setEquippedBadges: (badges: string[]) => void;
  addCompletedAchievement: (id: string) => void;
  dismissPendingAchievements: () => void;

  // 서버 상태 액션
  setGameProfile: (profile: GameProfile | null) => void;
  setIsGameLoading: (loading: boolean) => void;
  loadGameBootstrap: () => Promise<{
    profile: GameProfile | null;
    missions: CurrentMission[];
    isHealthLinked: boolean;
  }>;
  refreshGameState: () => Promise<{
    profile: GameProfile | null;
    missions: CurrentMission[];
    isHealthLinked: boolean;
  }>;
  levelUp: () => Promise<void>;
  clearGameState: () => void;

  // Auth / reset
  login: (user: User, rememberMe: boolean, token?: string) => void;
  updateUser: (patch: Partial<User>) => void;
  logout: () => void;
  deleteAccount: () => void;
  resetUserData: () => void;
  resetHealthcareLinkedData: () => void;

  setMissionInteractionState: (
    missionKey: string,
    value: MissionInteractionState
  ) => void;
  removeMissionInteractionState: (missionKey: string) => void;
  pruneMissionInteractionState: (validKeys: string[]) => void;
  clearMissionInteractionState: () => void;

  setMissionUiRequest: (patch: Partial<MissionUiRequestState>) => void;
  clearMissionUiRequest: () => void;
}




export const useAppStore = create<AppStore>()(
  persist(
    (set, get) => ({
      // Initial State
      ...INITIAL_AUTH_STATE,
      ...INITIAL_USER_DATA_STATE,
      ...INITIAL_GAME_STATE,
      ...INITIAL_SERVER_GAME_STATE,
      ...INITIAL_DEVICE_STATE,
      ...INITIAL_HISTORY_STATE,

      // =========================
      // Auth
      // =========================
      login: (user, rememberMe, token) =>
        set({
          ...INITIAL_USER_DATA_STATE,
          ...INITIAL_GAME_STATE,
          ...INITIAL_SERVER_GAME_STATE,
          ...INITIAL_HISTORY_STATE,
          isLoggedIn: true,
          user,
          rememberMe,
          authToken: token || null,
        }),

      logout: () => {
        localStorage.removeItem('access_token');
        localStorage.removeItem('token_type');
        localStorage.removeItem('auth_token');
        localStorage.removeItem(AUTO_LOGIN_KEY);

        set({
          ...INITIAL_AUTH_STATE,
          ...INITIAL_USER_DATA_STATE,
          ...INITIAL_GAME_STATE,
          ...INITIAL_SERVER_GAME_STATE,
          ...INITIAL_DEVICE_STATE,
          ...INITIAL_HISTORY_STATE,
        });
      },

      deleteAccount: () => {
        localStorage.removeItem('access_token');
        localStorage.removeItem('token_type');
        localStorage.removeItem('auth_token');
        localStorage.removeItem(AUTO_LOGIN_KEY);

        set({
          ...INITIAL_AUTH_STATE,
          ...INITIAL_USER_DATA_STATE,
          ...INITIAL_GAME_STATE,
          ...INITIAL_SERVER_GAME_STATE,
          ...INITIAL_DEVICE_STATE,
          ...INITIAL_HISTORY_STATE,
        });
      },

      setAuthToken: (token) => set({ authToken: token }),

      updateUser: (patch) =>
        set((state) => ({
          user: state.user ? { ...state.user, ...patch } : state.user,
        })),

      // =========================
      // Onboarding / Data
      // =========================
      setOnboardingComplete: (complete) =>
        set({
          hasCompletedOnboarding: complete,
        }),

      setInBodyData: (data) => {
        const state = get();

        const newState: Partial<AppStore> & {
          weightHistory?: WeightRecord[];
        } = {
          inBodyData: data,
          manualData: null,
          hasInBodyData: !!data,
          hasInBodySynced: !!data,
        };

        if (data) {
          const last = state.weightHistory[state.weightHistory.length - 1];
          if (!last || last.weight !== data.weight) {
            newState.weightHistory = [
              ...state.weightHistory,
              {
                weight: data.weight,
                recordedAt: new Date().toISOString(),
              },
            ];
          }
        }

        set(newState);
      },

      setManualData: (data) => {
        const state = get();

        const newState: Partial<AppStore> & {
          weightHistory?: WeightRecord[];
        } = {
          manualData: data,
          inBodyData: null,
          hasInBodyData: !!data,
          hasInBodySynced: false,
        };

        if (data) {
          const last = state.weightHistory[state.weightHistory.length - 1];
          if (!last || last.weight !== data.weight) {
            newState.weightHistory = [
              ...state.weightHistory,
              {
                weight: data.weight,
                recordedAt: new Date().toISOString(),
              },
            ];
          }
        }

        set(newState);
      },

      setActivityHistory: (records) => set({ activityHistory: records }),
      setWeightHistory: (records) => set({ weightHistory: records }),

      setPermissions: (permissions) =>
        set((state) => ({
          permissions: {
            ...state.permissions,
            ...permissions,
          },
        })),

      setWearableDevice: (device) => set({ wearableDevice: device }),

      setMissionsGenerated: (generated) => set({ hasMissionsGenerated: generated }),

      setMissions: (missions) => set({ missions }),

      setTargetWeight: (weight) => set({ targetWeight: weight }),

      setHealthLinked: (linked) =>
        set({
          isHealthLinked: linked,
          hasInBodyData: linked,
          hasInBodySynced: linked,
        }),

      // =========================
      // Game profile sync
      // =========================
      syncGameProfile: (profile) => {
        if (!profile) {
          set({
            gameProfile: null,
            hasCreatedCharacter: false,
            nickname: null,
            selectedCharacter: null,
            selectedBackground: null,
            ownedCharacters: [],
            ownedBackgroundIds: [],
            coins: 0,
            exp: 0,
            level: 1,
            requiredExp: 100,
            missionCoins: 0,
            equippedBadge: null,
            dailyMissionRegenCount: 0,
            dailyMissionRegenDate: null,
            canLevelUp: false,
            maxLevel: 10,
            characterStage: 'basic',
            completedAchievements: [],
            equippedBadges: [],
            totalMissionsCompleted: 0,
            totalCoinsEarned: 0,
          });
          return;
        }

        const dailyFreeRemaining =
          typeof profile.daily_free_regen_remaining === 'number'
            ? profile.daily_free_regen_remaining
            : 3;

        const ownedChars = profile.owned_characters ?? [];
        const selectedId = profile.selected_character_id ?? null;

        const activeChar = ownedChars.find(c => c.id === selectedId);
        const currentLevel = activeChar ? activeChar.level : (profile.level || 1);
        const currentExp = activeChar ? activeChar.exp : (profile.current_exp || 0);

        set({
          gameProfile: profile,
          hasCreatedCharacter: !!profile.has_created_character,
          nickname: profile.game_nickname ?? null,
          selectedCharacter: profile.selected_character_id ?? null,
          selectedBackground: profile.selected_background_id ?? null,
          ownedCharacters: ownedChars,
          ownedBackgroundIds: profile.owned_background_ids ?? [],
          coins: typeof profile.coins === 'number' ? profile.coins : 0,
          exp: currentExp,
          level: currentLevel,
          requiredExp:
            typeof profile.next_level_required_exp === 'number'
              ? profile.next_level_required_exp
              : 100,
          canLevelUp: !!profile.can_level_up,
          maxLevel: typeof profile.max_level === 'number' ? profile.max_level : 10,
          characterStage: profile.character_stage ?? 'basic',
          missionCoins:
            typeof profile.mission_coins === 'number' ? profile.mission_coins : 0,
          equippedBadge: profile.equipped_badge_id ?? null,
          dailyMissionRegenCount: Math.max(0, 3 - dailyFreeRemaining),
          dailyMissionRegenDate: profile.daily_regen_date ?? null,
          completedAchievements: profile.completed_achievement_codes ?? [],
          equippedBadges: profile.equipped_achievement_codes ?? [],
          totalMissionsCompleted:
            typeof profile.total_missions_completed === 'number'
              ? profile.total_missions_completed
              : 0,
          totalCoinsEarned:
            typeof profile.total_coins_earned === 'number'
              ? profile.total_coins_earned
              : 0,
        });
      },

      setGameProfile: (profile) => set({ gameProfile: profile }),

      setIsGameLoading: (loading) => set({ isGameLoading: loading }),

      // =========================
      // 서버 상태 로드
      // =========================
      loadGameBootstrap: async () => {
        set({ isGameLoading: true });

        try {
          const [healthResult, profileResult, missionsResult] = await Promise.all([
            healthcareApi.getLatestFast().catch(() => null),
            gameApi.getProfile().catch(() => null),
            missionsApi.getCurrent().catch(() => []),
          ]);

          const linked =
            !!healthResult?.inbody &&
            String(healthResult?.inbody?.source || '').toLowerCase() === 'healthconnect';
          const profile = profileResult?.profile ?? null;
          const missions = Array.isArray(missionsResult) ? missionsResult : [];

          set({
            isHealthLinked: linked,
            hasFetchedGameState: true,
            gameProfile: profile,
            missions,
            hasMissionsGenerated: missions.length > 0,
            hasInBodyData: linked,
            hasInBodySynced: linked,
          });

          get().syncGameProfile(profile);

          return {
            profile,
            missions,
            isHealthLinked: linked,
          };
        } finally {
          set({ isGameLoading: false });
        }
      },

      refreshGameState: async () => {
        try {
          const [healthResult, profileResult, missionsResult] = await Promise.all([
            healthcareApi.getLatestFast().catch(() => null),
            gameApi.getProfile().catch(() => null),
            missionsApi.getCurrent().catch(() => []),
          ]);

          const linked =
            !!healthResult?.inbody &&
            String(healthResult?.inbody?.source || '').toLowerCase() === 'healthconnect';
          const profile = profileResult?.profile ?? null;
          const missions = Array.isArray(missionsResult) ? missionsResult : [];

          set({
            isHealthLinked: linked,
            hasFetchedGameState: true,
            gameProfile: profile,
            missions,
            hasMissionsGenerated: missions.length > 0,
            hasInBodyData: linked,
            hasInBodySynced: linked,
          });

          get().syncGameProfile(profile);

          return {
            profile,
            missions,
            isHealthLinked: linked,
          };
        } catch (error) {
          console.error('refreshGameState 실패:', error);
          throw error;
        }
      },
      // ✅ 레벨업은 서버 단일 진실원(source of truth)
      // 로컬 계산으로 레벨/EXP를 조작하지 않고,
      // 서버가 반환한 profile 값으로만 상태를 갱신한다.
      levelUp: async () => {
        try{
          const result = await gameApi.levelUp();
          console.log("레벨업 서버 응답 데이터:", result); // 🔍 1. 서버 데이터 구조 확인용

          if (result?.profile) {
            // 1. 서버가 준 최신 프로필(업데이트된 캐릭터별 레벨 포함)로 전체 동기화
            get().syncGameProfile(result.profile);

            // 2. 현재 선택된 캐릭터의 새로운 레벨/경험치를 전역 상태(UI 반영용)에 즉시 업데이트
            const updatedChar = result.profile.owned_characters?.find(
              (c: any) => c.id === result.profile.selected_character_id
            );
            console.log("찾은 현재 캐릭터 데이터:", updatedChar); // 🔍 2. 데이터가 잘 찾아졌는지 확인
          
            if (updatedChar) {
              set({ 
                level: updatedChar.level, 
                exp: updatedChar.exp 
              });
            }
          }

          // 업적 축하 로직 (기존과 동일)
          if (result?.new_achievements?.length) {
            get().enqueueAchievementCelebration(
              result.new_achievements.map((a) => a.achievement_code)
            );
          }
        } catch (error) {
          console.error("레벨업 처리 중 에러 발생:", error);
        }
      },

      clearGameState: () =>
        set({
          ...INITIAL_GAME_STATE,
          ...INITIAL_SERVER_GAME_STATE,
          missions: [],
          hasMissionsGenerated: false,
        }),

      // =========================
      // Game local setters
      // =========================

      setMissionUiRequest: (patch) =>
        set((state) => ({
          missionUiRequest: {
            ...state.missionUiRequest,
            ...patch,
          },
        })),

      clearMissionUiRequest: () =>
        set({
          missionUiRequest: {
            refreshingSlot: null,
            submittingSlot: null,
            actionType: null,
            startedAt: null,
          },
        }),

      setMissionInteractionState: (missionKey, value) =>
        set((state) => ({
          missionInteractionState: {
            ...state.missionInteractionState,
            [missionKey]: value,
          },
        })),

      removeMissionInteractionState: (missionKey) =>
        set((state) => {
          const next = { ...state.missionInteractionState };
          delete next[missionKey];
          return { missionInteractionState: next };
        }),

      pruneMissionInteractionState: (validKeys) =>
        set((state) => {
          const next: Record<string, MissionInteractionState> = {};
          validKeys.forEach((key) => {
            if (state.missionInteractionState[key]) {
              next[key] = state.missionInteractionState[key];
            }
          });
          return { missionInteractionState: next };
        }),

      clearMissionInteractionState: () =>
        set({
          missionInteractionState: {},
        }),

      setCharacter: (characterId, backgroundId) =>
        set({
          selectedCharacter: characterId,
          selectedBackground: backgroundId,
          hasCreatedCharacter: true,
        }),

      setSelectedBackground: (backgroundId) =>
        set({ selectedBackground: backgroundId }),

      setSelectedCharacter: (characterId) =>
        set({ selectedCharacter: characterId }),
      //0409수정
      setOwnedCharacters: (characters) => set({ ownedCharacters: characters }),
      setOwnedBackgroundIds: (ids) => set({ ownedBackgroundIds: ids }),

      addCoins: (amount) =>
        set((state) => ({
          coins: state.coins + amount,
          totalCoinsEarned:
            amount > 0 ? state.totalCoinsEarned + amount : state.totalCoinsEarned,
        })),


      // ✅ EXP 적립만 로컬 반영
      // 실제 레벨 상승 / 필요 경험치 차감 / canLevelUp 계산은
      // 반드시 서버 levelUp() 응답 기준으로만 동기화한다.
      addExp: (amount) =>
        set((state) => {
          // 1. 현재 선택된 캐릭터를 찾음
          const newOwnedCharacters = state.ownedCharacters.map((char) => {
            if (char.id === state.selectedCharacter) {
              return { ...char, exp: char.exp + amount }; // 해당 캐릭터의 경험치만 증가
            }
            return char;
          });

          return {
            ownedCharacters: newOwnedCharacters,
            // 하위 호환성을 위해 전역 exp도 같이 업데이트 (PhotoCard 표시용)
            exp: state.exp + amount,
          };
        }),

      setEquippedBadge: (badgeId) => set({ equippedBadge: badgeId }),

      setNickname: (name) => set({ nickname: name }),

      setEquippedBadges: (badges) =>
        set({
          equippedBadges: badges.slice(0, 3),
        }),

      addCompletedAchievement: (id) =>
        set((state) => {
          if (state.completedAchievements.includes(id)) {
            return {};
          }

          return {
            completedAchievements: [...state.completedAchievements, id],
            pendingAchievements: [...state.pendingAchievements, id],
          };
        }),

      dismissPendingAchievements: () =>
        set((state) => ({
          pendingAchievements: state.pendingAchievements.slice(1),
        })),

      enqueueAchievementCelebration: (achievementCodes) =>
        set((state) => {
          const existing = new Set(state.pendingAchievements);
          const next = [...state.pendingAchievements];

          for (const code of achievementCodes) {
            if (!existing.has(code)) {
              existing.add(code);
              next.push(code);
            }
          }

          return {
            pendingAchievements: next,
          };
        }),

      addMissionCoins: (amount) =>
        set((state) => ({
          missionCoins: state.missionCoins + amount,
        })),

      useMissionCoin: () => {
        const state = get();

        if (state.missionCoins <= 0) return false;

        set({
          missionCoins: state.missionCoins - 1,
        });

        return true;
      },

      incrementDailyRegen: () =>
        set((state) => {
          const today = new Date().toISOString().split('T')[0];

          if (state.dailyMissionRegenDate !== today) {
            return {
              dailyMissionRegenCount: 1,
              dailyMissionRegenDate: today,
            };
          }

          return {
            dailyMissionRegenCount: state.dailyMissionRegenCount + 1,
          };
        }),

      getDailyRegenRemaining: () => {
        const state = get();
        const today = new Date().toISOString().split('T')[0];

        if (state.dailyMissionRegenDate !== today) return 3;

        return Math.max(0, 3 - state.dailyMissionRegenCount);
      },

      addActivityRecord: (steps, calories) =>
        set((state) => {
          const today = new Date().toISOString().split('T')[0];
          const filtered = state.activityHistory.filter((a) => a.date !== today);

          return {
            activityHistory: [...filtered, { date: today, steps, calories }],
          };
        }),

      addWeightRecord: (weight) =>
        set((state) => {
          const last = state.weightHistory[state.weightHistory.length - 1];
          if (last && last.weight === weight) return {};

          return {
            weightHistory: [
              ...state.weightHistory,
              {
                weight,
                recordedAt: new Date().toISOString(),
              },
            ],
          };
        }),

      // =========================
      // Reset
      // =========================
      resetUserData: () =>
        set({
          ...INITIAL_USER_DATA_STATE,
          ...INITIAL_GAME_STATE,
          ...INITIAL_SERVER_GAME_STATE,
          ...INITIAL_HISTORY_STATE,
        }),

      resetHealthcareLinkedData: () =>
        set((state) => ({
          ...state,
          hasCompletedOnboarding: false,
          hasInBodyData: false,
          hasInBodySynced: false,
          hasMissionsGenerated: false,
          inBodyData: null,
          manualData: null,
          targetWeight: null,
          missions: [],
          isHealthLinked: false,
          hasFetchedGameState: false,
          activityHistory: [],
          weightHistory: [],
        })),
    }),
    {
      name: 'health-quest-storage',
      partialize: (state) => {
        const sanitizedState = {
          ...state,
          pendingAchievements: [],
          isGameLoading: false,
          hasFetchedGameState: false,

          // ✅ 재생성/완료 요청 로딩 UI는 앱 재실행까지 가져가지 않음
          missionUiRequest: {
            refreshingSlot: null,
            submittingSlot: null,
            actionType: null,
            startedAt: null,
          },

          // ✅ missionInteractionState는 유지
          // B1/B2 타이머, B3 진행도, C1 완료 텍스트 유지용
          missionInteractionState: state.missionInteractionState,
        };

        if (state.rememberMe) {
          return sanitizedState;
        }

        return {
          ...sanitizedState,
          ...INITIAL_AUTH_STATE,
        };
      },
    }
  )
);