// src/components/game/gameData.ts

export interface CharacterItem {
  id: string;
  name: string;
  iconSrc: string;
  price: number;
  rarity?: 'common' | 'rare' | 'epic' | 'legendary';
  imageSrc?: string;
  scale?: number;
}

export interface BackgroundItem {
  id: string;
  name: string;
  gradient: string;
  price: number;
  rarity?: 'common' | 'rare' | 'epic' | 'legendary';
  imageSrc?: string;
}

export interface AchievementItem {
  id: string;
  title: string;
  description: string;
  badge: string;
  /** 업적 달성 조건 체크용 카테고리 */
  category: 'level' | 'mission' | 'coin' | 'purchase' | 'competition' | 'rank';
  /** 달성에 필요한 목표값 (레벨, 누적 횟수 등) */
  target?: number;
}

//
// 중요:
// 아래 id / price / rarity 는 백엔드 app/services/game_catalog.py 와 맞춰야 함
//

export const CHARACTERS: CharacterItem[] = [
  {
    id: 'char-default',
    name: '토끼 모험가',
    iconSrc: '/assets/head/rabbit_head.png',
    price: 0,
    rarity: 'common',
    scale: 0.6,
  },
  {
    id: 'char-bunny',
    name: '꼬꼬닭 어린이',
    iconSrc: '/assets/egg/egg_1.png',
    price: 100,
    rarity: 'common',
    scale: 0.4,
  },
  {
    id: 'char-bear',
    name: '여우 탐험가',
    iconSrc: '/assets/head/fox_head.png',
    price: 250,
    rarity: 'rare',
    scale: 0.6,
  },
  {
    id: 'char-cat',
    name: '곰곰 교수님',
    iconSrc: '/assets/head/bear_head.png',
    price: 400,
    rarity: 'epic',
    scale: 0.6,
  },
];

export const BACKGROUNDS: BackgroundItem[] = [
  {
    id: 'bg-default',
    name: '기본 초원',
    imageSrc: '/assets/backgrounds/bg_img_flower1.png',
    gradient: 'linear-gradient(180deg, #96cb59 0%, #6fa32f 45%, #45771c 100%)',
    price: 0,
    rarity: 'common',
  },
  {
    id: 'bg-sky',
    name: '비옥한 옥수수밭',
    imageSrc: '/assets/backgrounds/bg_img_crop1.png',
    gradient: 'linear-gradient(180deg, #89b959 0%, #6ab94b 45%, #589c30 100%)',
    price: 150,
    rarity: 'common',
  },
  {
    id: 'bg-sunset',
    name: '노을지는 바다',
    imageSrc: '/assets/backgrounds/bg_img_sunset1.png',
    gradient: 'linear-gradient(180deg, #f97316 0%, #e3773d 45%, #d66325 100%)',
    price: 300,
    rarity: 'rare',
  },
  {
    id: 'bg-night',
    name: '반짝 별밤 마을',
    imageSrc: '/assets/backgrounds/bg_img_night1.png',
    gradient: 'linear-gradient(180deg, #1e1b4b 0%, #312e81 45%, #020617 100%)',
    price: 500,
    rarity: 'epic',
  },
  {
    id: 'bg-galaxy',
    name: '낭만 가득 언덕',
    imageSrc: '/assets/backgrounds/bg_img_hill_1.png',
    gradient: 'linear-gradient(180deg, #581c87 0%, #7e22ce 45%, #030712 100%)',
    price: 800,
    rarity: 'legendary',
  },
];

export const ACHIEVEMENTS: AchievementItem[] = [
  // 레벨 업적
  {
    id: 'achv-level-2',
    title: '입문의 시작',
    description: '2레벨 달성',
    badge: '🪴',
    category: 'level',
    target: 2,
  },
  {
    id: 'achv-level-max',
    title: '성장의 증거',
    description: '만렙 달성',
    badge: '👑',
    category: 'level',
    target: 10, // 서버 만렙 기준과 통일
  },

  // 미션 누적 업적
  {
    id: 'achv-first-mission',
    title: '첫 발걸음',
    description: '첫 미션 달성',
    badge: '🌱',
    category: 'mission',
    target: 1,
  },
  {
    id: 'achv-mission-10',
    title: '미션 헌터',
    description: '미션 누적 10회 완료',
    badge: '🎯',
    category: 'mission',
    target: 10,
  },
  {
    id: 'achv-mission-50',
    title: '미션 전문가',
    description: '미션 누적 50회 완료',
    badge: '🏅',
    category: 'mission',
    target: 50,
  },
  {
    id: 'achv-mission-100',
    title: '미션 마스터',
    description: '미션 누적 100회 완료',
    badge: '🏆',
    category: 'mission',
    target: 100,
  },

  // 코인 누적 업적
  {
    id: 'achv-coin-10',
    title: '용돈 모으기',
    description: '코인 누적 10개 얻기',
    badge: '🪙',
    category: 'coin',
    target: 10,
  },
  {
    id: 'achv-coin-50',
    title: '저금통',
    description: '코인 누적 50개 얻기',
    badge: '💰',
    category: 'coin',
    target: 50,
  },
  {
    id: 'achv-coin-100',
    title: '금고 관리자',
    description: '코인 누적 100개 얻기',
    badge: '💎',
    category: 'coin',
    target: 100,
  },
  {
    id: 'achv-coin-200',
    title: '재벌의 길',
    description: '코인 누적 200개 얻기',
    badge: '🤑',
    category: 'coin',
    target: 200,
  },

  // 결제 업적
  {
    id: 'achv-first-purchase',
    title: '첫 결제!',
    description: '첫 미션 쿠폰 구매',
    badge: '🎁',
    category: 'purchase',
    target: 1,
  },

  // 경쟁전 업적
  {
    id: 'achv-week-walk-clear',
    title: 'First Stride',
    description: '첫 경쟁전 시즌 클리어',
    badge: '👟',
    category: 'competition',
    target: 1,
  },

  // 랭킹 업적
  {
    id: 'achv-rank-1',
    title: '전설의 챔피언',
    description: '경쟁전 1위 달성',
    /* 🏅 나중에 커스텀 훈장 아이콘으로 교체 예정: src/assets/badges/rank-1.png */
    badge: '🥇',
    category: 'rank',
    target: 1,
  },
  {
    id: 'achv-rank-2',
    title: '빛나는 준우승',
    description: '경쟁전 2위 달성',
    /* 🏅 나중에 커스텀 훈장 아이콘으로 교체 예정: src/assets/badges/rank-2.png */
    badge: '🥈',
    category: 'rank',
    target: 2,
  },
  {
    id: 'achv-rank-3',
    title: '동메달리스트',
    description: '경쟁전 3위 달성',
    /* 🏅 나중에 커스텀 훈장 아이콘으로 교체 예정: src/assets/badges/rank-3.png */
    badge: '🥉',
    category: 'rank',
    target: 3,
  },
  {
    id: 'achv-rank-top50',
    title: '탑 50 워커',
    description: '경쟁전 4~50위 달성',
    /* 🏅 나중에 커스텀 훈장 아이콘으로 교체 예정: src/assets/badges/rank-top50.png */
    badge: '⭐',
    category: 'rank',
    target: 50,
  },
  {
    id: 'achv-rank-top101',
    title: '건강한 도전자',
    description: '경쟁전 51~100위 달성',
    badge: '🏵️',
    category: 'rank',
    target: 100,
  },
];

////////////////////////////////////////////////////////////////////////////////////////////////
///////////////////////////////////////0409_코드 추가 작업//////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////////////////////
export interface OwnedCharacter {
  id: string;
  level: number;
  exp: number;
}

export type CharacterStage = 'basic' | 'middle' | 'advanced';

// 1~3: basic, 4~7: middle, 8~10: advanced 매핑
export const normalizeCharacterStage = (level: number): CharacterStage => {
  if (level <= 3) return 'basic';
  if (level <= 7) return 'middle';
  return 'advanced';
};

// 픽셀 이미지 경로 정의 (팀원의 index.tsx 경로를 public 경로로 변환)
export const CHARACTER_STAGE_FRAMES: Record<string, Record<CharacterStage, string[]>> = {
  'char-default': { // 기본 전사 (예시: 계란/닭 등 팀원 에셋으로 교체 가능)
    basic: [
      '/assets/rabbit/rabbit_1.png',
      '/assets/rabbit/rabbit_2.png',
      '/assets/rabbit/rabbit_3.png',
      '/assets/rabbit/rabbit_4.png',
    ],
    middle: [
      '/assets/rabbit/rabbit_level1_1.png',
      '/assets/rabbit/rabbit_level1_2.png',
      '/assets/rabbit/rabbit_level1_3.png',
      '/assets/rabbit/rabbit_level1_4.png',
    ],
    advanced: [
      '/assets/rabbit/rabbit_level2_1.png',
      '/assets/rabbit/rabbit_level2_2.png',
      '/assets/rabbit/rabbit_level2_3.png',
      '/assets/rabbit/rabbit_level2_4.png',
    ],
  },
  'char-bunny': {
    basic: [
      '/assets/egg/egg_1.png',
      '/assets/egg/egg_2.png',
      '/assets/egg/egg_1.png',
      '/assets/egg/egg_3.png',
    ],
    middle: [
      '/assets/egg/egg_level1_1.png',
      '/assets/egg/egg_level1_2.png',
      '/assets/egg/egg_level1_1.png',
      '/assets/egg/egg_level1_2.png',
    ],
    advanced: [
      '/assets/egg/egg_level2_1.png',
      '/assets/egg/egg_level2_2.png',
      '/assets/egg/egg_level2_1.png',
      '/assets/egg/egg_level2_2.png',
    ],
  },
  'char-bear': {
    basic: [
      '/assets/fox/fox_01.png',
      '/assets/fox/fox_02.png',
      '/assets/fox/fox_03.png',
      '/assets/fox/fox_04.png',
    ],
    middle: [
      '/assets/fox/fox_level1_1.png',
      '/assets/fox/fox_level1_2.png',
      '/assets/fox/fox_level1_3.png',
      '/assets/fox/fox_level1_4.png',

    ],
    advanced: [
      '/assets/fox/fox_level2_1.png',
      '/assets/fox/fox_level2_2.png',
      '/assets/fox/fox_level2_3.png',
      '/assets/fox/fox_level2_4.png',

    ],
  },
  'char-cat': {
    basic: [
      '/assets/bear/bear_01.png',
      '/assets/bear/bear_02.png',
      '/assets/bear/bear_03.png',
      '/assets/bear/bear_04.png',
    ],
    middle: [
      '/assets/bear/bear_level1_1.png',
      '/assets/bear/bear_level1_2.png',
      '/assets/bear/bear_level1_3.png',
      '/assets/bear/bear_level1_4.png',
    ],
    advanced: [
      '/assets/bear/bear_level2_1.png',
      '/assets/bear/bear_level2_2.png',
      '/assets/bear/bear_level2_3.png',
      '/assets/bear/bear_level2_4.png',
    ],
  },
};