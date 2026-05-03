// src/services/api.ts
import type { AchievementRecord } from '@/types';
import type {
  ApiErrorResponse,
  CheckUserDataResponse,
  CompleteSlotRequest,
  CompleteSlotResponse,
  CurrentMission,
  EquipBackgroundRequest,
  EquipCharacterRequest,
  GameProfileResponse,
  GenerateInitialMissionsRequest,
  GenerateInitialMissionsResponse,
  InitializeCharacterRequest,
  InitializeCharacterResponse,
  LatestHealthcareResponse,
  LevelUpResponse,
  LoginRequest,
  LoginResponse,
  PurchaseBackgroundRequest,
  PurchaseCharacterRequest,
  RefreshSlotRequest,
  RefreshSlotResponse,
  ResetDailyRegenResponse,
  SignupRequest,
  SyncHealthcareRequest,
  SyncHistoryRequest,
  UnlinkHealthcareResponse,
  UseMissionCoinResponse,
  StartSlotRequest,
  StartSlotResponse,
  UpdateGameNicknameRequest,
  UpdateGameNicknameResponse,
  GetAchievementsResponse,
  EquipAchievementsRequest,
  EquipAchievementsResponse,
  RetrySlotRequest,
  RetrySlotResponse,
  PurchaseCharacterResponse,
  PurchaseBackgroundResponse,
  WeekWalkOverviewResponse,
  WeekWalkJoinResponse,
  ProfileDetailsResponse,
  UpdateProfileDetailsRequest,
  UpdateImagePermissionRequest,
  UpdateImagePermissionResponse,
} from '@/types';

// 백엔드 주소
const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || 'http://192.168.0.4:8000';

// --------------------------------------------
// 토큰 관련
// --------------------------------------------
const AUTH_TOKEN_KEY = 'auth_token';

export const getAuthToken = (): string | null => {
  return (
    localStorage.getItem(AUTH_TOKEN_KEY) ||
    localStorage.getItem('access_token')
  );
};

export const setAuthToken = (token: string): void => {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
};

export const removeAuthToken = (): void => {
  localStorage.removeItem(AUTH_TOKEN_KEY);
};

// --------------------------------------------
// 공통 에러 처리
// --------------------------------------------
const parseErrorMessage = async (response: Response): Promise<string> => {
  try {
    const errorData = (await response.json()) as ApiErrorResponse;
    return (
      errorData.detail ||
      errorData.message ||
      `요청에 실패했습니다. (${response.status})`
    );
  } catch {
    return `요청에 실패했습니다. (${response.status})`;
  }
};

// --------------------------------------------
// 공통 fetch
// --------------------------------------------
const fetchWithAuth = async (
  path: string,
  options: RequestInit = {}
): Promise<Response> => {
  const token = getAuthToken();

  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  return response;
};

const requestJson = async <T>(
  path: string,
  options: RequestInit = {}
): Promise<T> => {
  const response = await fetchWithAuth(path, options);

  if (!response.ok) {
    throw new Error(await parseErrorMessage(response));
  }

  return response.json() as Promise<T>;
};

// --------------------------------------------
// Auth API
// --------------------------------------------
export const authApi = {
  signup: async (
    data: SignupRequest
  ): Promise<{ message?: string; user_id?: number }> => {
    return requestJson('/auth/signup', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  login: async (data: LoginRequest): Promise<LoginResponse> => {
    const result = await requestJson<LoginResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    });

    if (result.access_token) {
      setAuthToken(result.access_token);
    }

    return result;
  },

  updateProfile: async (nickname: string): Promise<{ message?: string }> => {
    return requestJson(
      `/auth/update-profile?nickname=${encodeURIComponent(nickname)}`,
      {
        method: 'PATCH',
      }
    );
  },

  changePassword: async (
    currentPassword: string,
    newPassword: string
  ): Promise<{ message?: string }> => {
    return requestJson('/auth/change-password', {
      method: 'PATCH',
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });
  },

  logout: async (): Promise<{ message?: string }> => {
    return requestJson('/auth/logout', {
      method: 'POST',
    });
  },

  deleteAccount: async (): Promise<{ ok?: boolean; message?: string }> => {
    return requestJson('/auth/delete-account', {
      method: 'DELETE',
    });
  },
};



// --------------------------------------------
// Profile Details API
// --------------------------------------------
export const profileApi = {
  getDetails: async (): Promise<ProfileDetailsResponse> => {
    return requestJson('/auth/profile-details', {
      method: 'GET',
    });
  },

  updateDetails: async (
    data: UpdateProfileDetailsRequest
  ): Promise<ProfileDetailsResponse> => {
    return requestJson('/auth/profile-details', {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  updateImagePermission: async (
    data: UpdateImagePermissionRequest
  ): Promise<UpdateImagePermissionResponse> => {
    return requestJson('/auth/image-permission', {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },
};

// --------------------------------------------
// Healthcare API
// --------------------------------------------
export const healthcareApi = {
  sync: async (data: SyncHealthcareRequest): Promise<any> => {
    return requestJson('/healthcare/sync', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  syncHistory: async (data: SyncHistoryRequest): Promise<any> => {
    return requestJson('/healthcare/sync-history', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  getLatestFast: async (): Promise<LatestHealthcareResponse> => {
    return requestJson('/healthcare/latest-fast', {
      method: 'GET',
    });
  },

  getLatest: async (): Promise<any> => {
    return requestJson('/healthcare/latest', {
      method: 'GET',
    });
  },

  getAverage: async (): Promise<any> => {
    return requestJson('/healthcare/average', {
      method: 'GET',
    });
  },

  updateTargetWeight: async (
    targetWeight: number
  ): Promise<{ ok: boolean; target_weight: number; inbody_id: number }> => {
    return requestJson('/healthcare/target-weight', {
      method: 'PATCH',
      body: JSON.stringify({
        target_weight: targetWeight,
      }),
    });
  },

  unlink: async (): Promise<UnlinkHealthcareResponse> => {
    return requestJson('/healthcare/unlink', {
      method: 'DELETE',
    });
  },
};

// --------------------------------------------
// Missions API
// --------------------------------------------
export const missionsApi = {
  checkUserData: async (): Promise<CheckUserDataResponse> => {
    return requestJson('/missions/check-data', {
      method: 'GET',
    });
  },

  getCurrent: async (): Promise<CurrentMission[]> => {
    return requestJson('/missions/current', {
      method: 'GET',
    });
  },

  startSlot: async (data: StartSlotRequest): Promise<StartSlotResponse> => {
    return requestJson('/missions/start-slot', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  retrySlot: async (data: RetrySlotRequest): Promise<RetrySlotResponse> => {
    return requestJson('/missions/retry-slot', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },


  generateInitial: async (
    data: GenerateInitialMissionsRequest = { force_regenerate: false }
  ): Promise<GenerateInitialMissionsResponse> => {
    return requestJson('/missions/generate-initial', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  refreshSlot: async (data: RefreshSlotRequest): Promise<RefreshSlotResponse> => {
    return requestJson('/missions/refresh-slot', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  completeSlot: async (data: CompleteSlotRequest): Promise<CompleteSlotResponse> => {
    return requestJson('/missions/complete-slot', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
};

// --------------------------------------------
// Game API
// --------------------------------------------
export const gameApi = {
  getProfile: async (): Promise<GameProfileResponse> => {
    return requestJson('/game/profile', {
      method: 'GET',
    });
  },

  getAchievements: async (): Promise<GetAchievementsResponse> => {
    return requestJson('/game/achievements', {
      method: 'GET',
    });
  },

  equipAchievements: async (
    data: EquipAchievementsRequest
  ): Promise<EquipAchievementsResponse> => {
    return requestJson('/game/equip-achievements', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  updateGameNickname: async (
    data: UpdateGameNicknameRequest
  ): Promise<UpdateGameNicknameResponse> => {
    return requestJson('/game/update-game-nickname', {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  initializeCharacter: async (
    data: InitializeCharacterRequest
  ): Promise<InitializeCharacterResponse> => {
    return requestJson('/game/initialize-character', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  purchaseCharacter: async (
    data: PurchaseCharacterRequest
  ): Promise<PurchaseCharacterResponse> => {
    return requestJson('/game/purchase-character', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  purchaseBackground: async (
    data: PurchaseBackgroundRequest
  ): Promise<PurchaseBackgroundResponse> => {
    return requestJson('/game/purchase-background', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  equipCharacter: async (data: EquipCharacterRequest): Promise<any> => {
    return requestJson('/game/equip-character', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  equipBackground: async (data: EquipBackgroundRequest): Promise<any> => {
    return requestJson('/game/equip-background', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  useMissionCoin: async (): Promise<UseMissionCoinResponse> => {
    return requestJson('/game/use-mission-coin', {
      method: 'POST',
    });
  },

  purchaseMissionCoins: async (
    data: PurchaseMissionCoinsRequest
  ): Promise<PurchaseMissionCoinsResponse> => {
    return requestJson('/game/purchase-mission-coins', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  checkGameNicknameAvailability: async (payload: { game_nickname: string }) => {
    return requestJson<{
      available: boolean;
      message?: string;
    }>('/game/check-game-nickname', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  resetDailyRegenIfNeeded: async (): Promise<ResetDailyRegenResponse> => {
    return requestJson('/game/reset-daily-regen-if-needed', {
      method: 'POST',
    });
  },

  levelUp: async (): Promise<LevelUpResponse> => {
    return requestJson('/game/level-up', {
      method: 'POST',
    });
  },
};

export interface CreateMissionCouponOrderRequest {
  package_id: string;
}

export interface CreateMissionCouponOrderResponse {
  ok: boolean;
  order_id: string;
  order_name: string;
  amount: number;
  coupon_amount: number;
  package_id: string;
  customer_key: string;
}

export interface TossConfirmRequest {
  paymentKey: string;
  orderId: string;
  amount: number;
}

export interface TossConfirmResponse {
  ok: boolean;
  message: string;
  order_id?: string;
  package_id?: string;
  purchased_amount?: number;
  mission_coins?: number;
  profile: GameProfileResponse['profile'];
  new_achievements?: AchievementRecord[];
}

export const paymentsApi = {
  createMissionCouponOrder: async (
    data: CreateMissionCouponOrderRequest
  ): Promise<CreateMissionCouponOrderResponse> => {
    return requestJson('/payments/mission-coupons/orders', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  confirmTossPayment: async (
    data: TossConfirmRequest
  ): Promise<TossConfirmResponse> => {
    return requestJson('/payments/toss/confirm', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
};


export const weekWalkApi = {
  getOverview: async (): Promise<WeekWalkOverviewResponse> => {
    return requestJson('/week-walk/overview', {
      method: 'GET',
    });
  },

  join: async (): Promise<WeekWalkJoinResponse> => {
    return requestJson('/week-walk/join', {
      method: 'POST',
    });
  },
};

export interface PurchaseMissionCoinsRequest {
  package_id: string;
}

export interface PurchaseMissionCoinsResponse {
  ok: boolean;
  message: string;
  package_id: string;
  purchased_amount: number;
  mission_coins: number;
  profile: GameProfileResponse['profile'];
  new_achievements?: AchievementRecord[];
}


// --------------------------------------------
// System API
// --------------------------------------------
export const systemApi = {
  healthCheck: async (): Promise<boolean> => {
    try {
      const response = await fetch(`${API_BASE_URL}/`);
      return response.ok;
    } catch {
      return false;
    }
  },
};