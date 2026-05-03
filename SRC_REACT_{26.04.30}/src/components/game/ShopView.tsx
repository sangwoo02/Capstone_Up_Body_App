/**
 * 🛒 상점 뷰 - 서버 구매/장착 연동 + 닉네임 변경권 + 구매 확인 모달
 */

import { useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Coins,
  Lock,
  ShoppingBag,
  Palette,
  UserRound,
  PenLine,
  AlertTriangle,
  Sword,
  Sparkles,
} from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import { toast } from 'sonner';
import { gameApi } from '@/services/api';
import CharacterSelectDialog from './CharacterSelectDialog';
import {
  BACKGROUNDS,
  CHARACTERS,
  type BackgroundItem,
  type CharacterItem,
} from './gameData';

type ShopTab = 'character' | 'background';

const rarityStyles: Record<string, string> = {
  common: 'text-slate-200 border-slate-300/20 bg-slate-500/15',
  rare: 'text-sky-200 border-sky-300/20 bg-sky-500/15',
  epic: 'text-violet-200 border-violet-300/20 bg-violet-500/15',
  legendary: 'text-yellow-200 border-yellow-300/20 bg-yellow-500/15',
};

const rarityLabelMap: Record<string, string> = {
  common: 'COMMON',
  rare: 'RARE',
  epic: 'EPIC',
  legendary: 'LEGENDARY',
};

/** 구매 확인 모달 */
const PurchaseConfirmDialog = ({
  open,
  onClose,
  onConfirm,
  itemName,
  itemType,
  price,
  currentCoins,
  submitting,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  itemName: string;
  itemType: 'character' | 'background';
  price: number;
  currentCoins: number;
  submitting: boolean;
}) => {
  if (!open) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-[70] flex items-center justify-center p-4"
      >
        <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />

        <motion.div
          initial={{ scale: 0.92, y: 8 }}
          animate={{ scale: 1, y: 0 }}
          exit={{ scale: 0.92, y: 8 }}
          className="relative w-full max-w-[330px] rounded-[28px] p-[1px] bg-gradient-to-b from-yellow-300/35 via-orange-300/15 to-white/5"
        >
          <div className="relative overflow-hidden rounded-[27px] border border-yellow-300/15 bg-[linear-gradient(to_bottom,_rgba(255,171,64,0.14),_rgba(255,255,255,0.04))] p-5">
            <div className="absolute inset-x-4 top-2 h-10 rounded-full bg-white/10 blur-lg" />

            <div className="relative flex items-center gap-2 mb-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-b from-yellow-400 to-orange-500 flex items-center justify-center shadow-[0_4px_0_rgba(146,64,14,0.9)]">
                <AlertTriangle className="w-5 h-5 text-white" />
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-[0.18em] text-yellow-100/70 font-bold">
                  Purchase Confirm
                </p>
                <h3 className="font-black text-white">정말 구매하시겠습니까?</h3>
              </div>
            </div>

            <div className="rounded-2xl border border-white/10 bg-white/[0.04] px-3 py-3 mb-3">
              <p className="text-sm text-white font-bold">{itemName}</p>
              <p className="text-[11px] text-white/55 mt-1">
                {itemType === 'character' ? '캐릭터 아이템' : '배경 아이템'}
              </p>
            </div>

            <p className="text-sm text-white/70 mb-3 leading-relaxed">
              {itemType === 'character'
                ? '구매 후 기존 캐릭터는 보관함으로 이동되며, 새 캐릭터가 즉시 장착됩니다.'
                : '구매 후 기존 배경은 보관함으로 이동되며, 새 배경이 즉시 적용됩니다.'}
            </p>

            <div className="grid grid-cols-2 gap-2 mb-4">
              <div className="rounded-2xl border border-yellow-300/15 bg-yellow-500/10 px-3 py-3">
                <div className="flex items-center gap-2 mb-1">
                  <Coins className="w-4 h-4 text-yellow-300" />
                  <span className="text-[11px] text-yellow-100/70 font-bold">보유 코인</span>
                </div>
                <p className="text-base font-black text-yellow-200">{currentCoins}</p>
              </div>

              <div className="rounded-2xl border border-orange-300/15 bg-orange-500/10 px-3 py-3">
                <div className="flex items-center gap-2 mb-1">
                  <ShoppingBag className="w-4 h-4 text-orange-300" />
                  <span className="text-[11px] text-orange-100/70 font-bold">구매 가격</span>
                </div>
                <p className="text-base font-black text-orange-200">{price}</p>
              </div>
            </div>

            <div className="flex gap-2">
              <button
                onClick={onClose}
                disabled={submitting}
                className="flex-1 h-12 rounded-2xl bg-white/10 border border-white/10 text-white/75 text-sm font-bold disabled:opacity-50"
              >
                아니요
              </button>
              <button
                onClick={onConfirm}
                disabled={submitting}
                className="flex-1 h-12 rounded-2xl border border-yellow-100/20 bg-gradient-to-b from-yellow-400 via-orange-400 to-orange-600 text-white text-sm font-black shadow-[0_5px_0_rgba(146,64,14,0.95)] active:translate-y-[3px] active:shadow-[0_2px_0_rgba(146,64,14,0.95)] disabled:opacity-60"
              >
                {submitting ? '처리 중...' : '구매하기'}
              </button>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};

const ShopView = () => {
  const {
    coins,
    hasCreatedCharacter,
    selectedCharacter,
    selectedBackground,
    ownedCharacters,
    ownedBackgroundIds,
    refreshGameState,
    enqueueAchievementCelebration,
  } = useAppStore();

  const [activeTab, setActiveTab] = useState<ShopTab>('character');
  const [pendingItemId, setPendingItemId] = useState<string | null>(null);
  const [showNicknameDialog, setShowNicknameDialog] = useState(false);

  const [purchaseTarget, setPurchaseTarget] = useState<{
    item: CharacterItem | BackgroundItem;
    type: 'character' | 'background';
  } | null>(null);

  const selectedCharacterData = useMemo(
    () => CHARACTERS.find((c) => c.id === selectedCharacter) ?? CHARACTERS[0],
    [selectedCharacter]
  );

  const currentBgData = useMemo(() => 
    BACKGROUNDS.find(bg => bg.id === selectedBackground),
    [selectedBackground]
  );

  const selectedBackgroundData = useMemo(
    () => BACKGROUNDS.find((b) => b.id === selectedBackground) ?? BACKGROUNDS[0],
    [selectedBackground]
  );

  const handlePurchaseRequest = (item: CharacterItem | BackgroundItem, type: 'character' | 'background') => {
    const isOwned =
      type === 'character'
        ? ownedCharacters.some((oc) => oc.id === item.id) || item.price === 0
        : ownedBackgroundIds.includes(item.id) || item.price === 0;

    if (isOwned) {
      toast.error('이미 보유한 아이템입니다.');
      return;
    }

    if (coins < item.price) {
      toast.error('코인이 부족하여 구매할 수 없습니다.');
      return;
    }

    setPurchaseTarget({ item, type });
  };

  const handlePurchaseConfirm = async () => {
    if (!purchaseTarget) return;
    const { item, type } = purchaseTarget;

    try {
      setPendingItemId(item.id);

      let result: any;

      if (type === 'character') {
        result = await gameApi.purchaseCharacter({ character_id: item.id });
      } else {
        result = await gameApi.purchaseBackground({ background_id: item.id });
      }

      if (result?.new_achievements?.length) {
        enqueueAchievementCelebration(
          result.new_achievements.map((a: any) => a.achievement_code)
        );
      }

      await refreshGameState();

      if (type === 'character') {
        toast.success(`"${item.name}" 구매 후 바로 장착되었습니다!`);
      } else {
        toast.success(`"${item.name}" 구매 후 바로 적용되었습니다!`);
      }
      setPurchaseTarget(null);
    } catch (error: any) {
      console.error('구매 실패:', error);
      toast.error(error?.message || '구매에 실패했습니다.');
    } finally {
      setPendingItemId(null);
    }
  };

  const handleEquipCharacter = async (item: CharacterItem) => {
    try {
      setPendingItemId(item.id);
      await gameApi.equipCharacter({ character_id: item.id });
      await refreshGameState();
      toast.success(`"${item.name}" 캐릭터를 장착했습니다.`);
    } catch (error: any) {
      console.error('캐릭터 장착 실패:', error);
      toast.error(error?.message || '캐릭터 장착에 실패했습니다.');
    } finally {
      setPendingItemId(null);
    }
  };

  const handleEquipBackground = async (item: BackgroundItem) => {
    try {
      setPendingItemId(item.id);
      await gameApi.equipBackground({ background_id: item.id });
      await refreshGameState();
      toast.success(`"${item.name}" 배경을 적용했습니다.`);
    } catch (error: any) {
      console.error('배경 장착 실패:', error);
      toast.error(error?.message || '배경 적용에 실패했습니다.');
    } finally {
      setPendingItemId(null);
    }
  };

  const handleNicknameChange = () => {
    if (coins < 500) {
      toast.error('코인이 부족하여 닉네임을 변경할 수 없습니다. (500코인 필요)');
      return;
    }

    setShowNicknameDialog(true);
  };

  const renderCharacterCard = (item: CharacterItem) => {
    const isOwned = ownedCharacters.some((oc) => oc.id === item.id) || item.price === 0;
    const isSelected = selectedCharacter === item.id;
    const canAfford = coins >= item.price;
    const isPending = pendingItemId === item.id;

    return (
      <motion.div
        key={item.id}
        whileTap={{ scale: 0.985 }}
        className={`relative overflow-hidden rounded-[28px] p-[1px] ${
          isSelected
            ? 'bg-gradient-to-b from-violet-300/30 via-pink-300/10 to-white/5'
            : 'bg-gradient-to-b from-white/15 to-white/5'
        }`}
      >
        <div
          className={`relative rounded-[27px] border p-4 backdrop-blur-md ${
            isSelected
              ? 'border-violet-300/15 bg-[linear-gradient(to_bottom,_rgba(168,85,247,0.12),_rgba(255,255,255,0.03))]'
              : 'border-white/5 bg-[linear-gradient(to_bottom,_rgba(255,255,255,0.05),_rgba(255,255,255,0.02))]'
          }`}
        >
          <div className="absolute inset-x-4 top-2 h-10 rounded-full bg-white/8 blur-lg pointer-events-none" />

          <div className="relative flex items-start justify-between gap-3">
            <div className="flex items-center gap-3 min-w-0">
              <div className="w-16 h-16 rounded-[20px] bg-[linear-gradient(to_bottom,_rgba(255,255,255,0.12),_rgba(255,255,255,0.05))] border border-white/10 flex items-center justify-center text-[34px] shrink-0 shadow-[0_5px_0_rgba(0,0,0,0.2)]">
                {item.iconSrc ? (
                  <img 
                    src={item.iconSrc} 
                    alt={item.name}
                    className="w-full h-full object-contain p-2"
                    style={{ transform: `scale(${item.scale || 1})` }}
                  />
                ) : (
                  // 아이콘 경로가 없을 경우를 대비한 대체 텍스트
                  <span className="text-2xl">👤</span>
                  )}
                </div>

              <div className="min-w-0">
                <p className="text-[15px] font-black text-white truncate">{item.name}</p>

                <div
                  className={`inline-flex mt-1 text-[10px] px-2.5 py-1 rounded-full border font-black tracking-[0.12em] ${
                    rarityStyles[item.rarity || 'common']
                  }`}
                >
                  {rarityLabelMap[item.rarity || 'common'] || (item.rarity || 'common').toUpperCase()}
                </div>
              </div>
            </div>

            {isSelected && (
              <div className="shrink-0 text-[10px] px-2.5 py-1 rounded-full border border-violet-300/20 bg-violet-500/15 text-violet-200 font-black">
                장착중
              </div>
            )}
          </div>

          <div className="mt-4 rounded-2xl border border-white/8 bg-white/[0.03] px-3 py-3 flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-yellow-300">
              <Coins className="w-4 h-4" />
              <span className="text-base font-black">{item.price}</span>
            </div>

            {isOwned ? (
              isSelected ? (
                <button
                  disabled
                  className="h-11 px-4 rounded-2xl text-xs font-black bg-white/5 border border-white/10 text-white/30 cursor-not-allowed"
                >
                  사용 중
                </button>
              ) : (
                <button
                  onClick={() => handleEquipCharacter(item)}
                  disabled={isPending}
                  className="h-11 px-4 rounded-2xl text-xs font-black border border-violet-200/15 bg-gradient-to-b from-violet-500 to-fuchsia-600 text-white shadow-[0_4px_0_rgba(91,33,182,0.9)] active:translate-y-[2px] active:shadow-[0_2px_0_rgba(91,33,182,0.9)] disabled:opacity-60"
                >
                  {isPending ? '처리중...' : '장착'}
                </button>
              )
            ) : (
              <button
                onClick={() => handlePurchaseRequest(item, 'character')}
                disabled={!canAfford || isPending}
                className={`h-11 px-4 rounded-2xl text-xs font-black border disabled:opacity-60 ${
                  canAfford
                    ? 'border-yellow-100/20 bg-gradient-to-b from-yellow-400 via-orange-400 to-orange-600 text-white shadow-[0_4px_0_rgba(146,64,14,0.95)] active:translate-y-[2px] active:shadow-[0_2px_0_rgba(146,64,14,0.95)]'
                    : 'bg-white/5 text-white/25 border-white/10 cursor-not-allowed'
                }`}
              >
                {isPending ? '처리중...' : '구매'}
              </button>
            )}
          </div>

          {!isOwned && !canAfford && (
            <p className="text-[11px] text-red-300/85 mt-2 font-medium">코인이 부족합니다.</p>
          )}
        </div>
      </motion.div>
    );
  };

  const renderBackgroundCard = (item: BackgroundItem) => {
    const isOwned = ownedBackgroundIds.includes(item.id) || item.price === 0;
    const isSelected = selectedBackground === item.id;
    const canAfford = coins >= item.price;
    const isPending = pendingItemId === item.id;

    return (
      <motion.div
        key={item.id}
        whileTap={{ scale: 0.985 }}
        className={`relative overflow-hidden rounded-[28px] p-[1px] ${
          isSelected
            ? 'bg-gradient-to-b from-sky-300/30 via-cyan-300/10 to-white/5'
            : 'bg-gradient-to-b from-white/15 to-white/5'
        }`}
      >
        <div
          className={`relative rounded-[27px] border p-4 backdrop-blur-md ${
            isSelected
              ? 'border-cyan-300/15 bg-[linear-gradient(to_bottom,_rgba(34,211,238,0.1),_rgba(255,255,255,0.03))]'
              : 'border-white/5 bg-[linear-gradient(to_bottom,_rgba(255,255,255,0.05),_rgba(255,255,255,0.02))]'
          }`}
        >
          <div className="absolute inset-x-4 top-2 h-10 rounded-full bg-white/8 blur-lg pointer-events-none" />

          <div className="relative w-full h-24 rounded-2xl border border-white/10 shadow-[0_5px_0_rgba(0,0,0,0.2)] overflow-hidden">
            {item.imageSrc ? (
              <img 
                src={item.imageSrc} 
                alt={item.name}
                className="w-full h-full object-cover" 
              />
            ) : (
              // imageSrc가 없을 경우를 대비한 기존 그라데이션 유지 (fallback)
              <div className="w-full h-full" style={{ background: item.gradient }} />
            )}
          </div>

          <div className="mt-3 flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[15px] font-black text-white truncate">{item.name}</p>

              <div
                className={`inline-flex mt-1 text-[10px] px-2.5 py-1 rounded-full border font-black tracking-[0.12em] ${
                  rarityStyles[item.rarity || 'common']
                }`}
              >
                {rarityLabelMap[item.rarity || 'common'] || (item.rarity || 'common').toUpperCase()}
              </div>
            </div>

            {isSelected && (
              <div className="shrink-0 text-[10px] px-2.5 py-1 rounded-full border border-cyan-300/20 bg-cyan-500/15 text-cyan-200 font-black">
                사용중
              </div>
            )}
          </div>

          <div className="mt-4 rounded-2xl border border-white/8 bg-white/[0.03] px-3 py-3 flex items-center justify-between">
            <div className="flex items-center gap-1.5 text-yellow-300">
              <Coins className="w-4 h-4" />
              <span className="text-base font-black">{item.price}</span>
            </div>

            {isOwned ? (
              isSelected ? (
                <button
                  disabled
                  className="h-11 px-4 rounded-2xl text-xs font-black bg-white/5 border border-white/10 text-white/30 cursor-not-allowed"
                >
                  사용 중
                </button>
              ) : (
                <button
                  onClick={() => handleEquipBackground(item)}
                  disabled={isPending}
                  className="h-11 px-4 rounded-2xl text-xs font-black border border-cyan-100/15 bg-gradient-to-b from-cyan-500 to-blue-600 text-white shadow-[0_4px_0_rgba(8,145,178,0.95)] active:translate-y-[2px] active:shadow-[0_2px_0_rgba(8,145,178,0.95)] disabled:opacity-60"
                >
                  {isPending ? '처리중...' : '적용'}
                </button>
              )
            ) : (
              <button
                onClick={() => handlePurchaseRequest(item, 'background')}
                disabled={!canAfford || isPending}
                className={`h-11 px-4 rounded-2xl text-xs font-black border disabled:opacity-60 ${
                  canAfford
                    ? 'border-yellow-100/20 bg-gradient-to-b from-yellow-400 via-orange-400 to-orange-600 text-white shadow-[0_4px_0_rgba(146,64,14,0.95)] active:translate-y-[2px] active:shadow-[0_2px_0_rgba(146,64,14,0.95)]'
                    : 'bg-white/5 text-white/25 border-white/10 cursor-not-allowed'
                }`}
              >
                {isPending ? '처리중...' : '구매'}
              </button>
            )}
          </div>

          {!isOwned && !canAfford && (
            <p className="text-[11px] text-red-300/85 mt-2 font-medium">코인이 부족합니다.</p>
          )}
        </div>
      </motion.div>
    );
  };

  if (!hasCreatedCharacter) {
    return (
      <div className="flex-1 overflow-y-auto px-5 pb-4">
        <div className="relative overflow-hidden rounded-[28px] p-[1px] bg-gradient-to-b from-violet-300/25 via-white/10 to-white/5">
          <div className="rounded-[27px] border border-white/5 bg-[linear-gradient(to_bottom,_rgba(255,255,255,0.06),_rgba(255,255,255,0.03))] p-5 text-center">
            <div className="w-16 h-16 mx-auto rounded-[20px] bg-gradient-to-b from-violet-500 to-fuchsia-600 border border-violet-200/15 flex items-center justify-center mb-3 shadow-[0_5px_0_rgba(91,33,182,0.9)]">
              <Lock className="w-7 h-7 text-white" />
            </div>

            <p className="text-white font-black">상점을 이용하려면 닉네임 설정이 필요합니다</p>
            <p className="text-white/55 text-sm mt-2">
              먼저 홈 화면에서 닉네임을 설정해주세요.
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-5 pb-4">
      <motion.div
        initial={false}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.12 }}
        className="space-y-4"
      >
        {/* 상점 헤더 패널 */}
        <div className="relative overflow-hidden rounded-[30px] p-[1px] bg-gradient-to-b from-yellow-300/25 via-orange-300/10 to-white/5">
          <div className="relative rounded-[29px] border border-white/5 bg-[linear-gradient(to_bottom,_rgba(255,255,255,0.06),_rgba(255,255,255,0.03))] backdrop-blur-md p-4">
            <div className="absolute inset-x-4 top-2 h-12 rounded-full bg-white/10 blur-xl" />
            <div className="absolute -right-6 -top-6 w-24 h-24 bg-yellow-400/10 rounded-full blur-2xl" />

            <div className="relative flex items-center gap-3 mb-4">
              <div className="w-12 h-12 rounded-2xl bg-gradient-to-b from-yellow-400 to-orange-500 flex items-center justify-center shadow-[0_5px_0_rgba(146,64,14,0.95)]">
                <ShoppingBag className="w-6 h-6 text-white" />
              </div>

              <div className="min-w-0">
                <p className="text-[11px] uppercase tracking-[0.2em] text-yellow-100/70 font-bold">
                  Battle Shop
                </p>
                <h2 className="text-xl font-black text-white leading-none">상점</h2>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-2xl border border-violet-300/10 bg-violet-500/10 p-3">
                <div className="flex items-center gap-2 mb-2">
                  <UserRound className="w-4 h-4 text-violet-200" />
                  <span className="text-[11px] text-white/60 font-bold tracking-wide">현재 캐릭터</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-11 h-11 rounded-2xl bg-white/10 border border-white/10 flex items-center justify-center overflow-hidden shadow-[0_4px_0_rgba(0,0,0,0.2)]">
                    {selectedCharacterData?.iconSrc ? (
                      <img 
                        src={selectedCharacterData.iconSrc} 
                        alt={selectedCharacterData.name}
                        className="w-full h-full object-contain p-1"
                        style={{ transform: `scale(${selectedCharacterData.scale || 1})` }}
                      />
                    ) : (
                      /* 만약 iconSrc가 없을 때를 대비해 emoji를 남겨두고 싶다면, 
                        interface CharacterItem { emoji?: string; } 처럼 물음표를 붙여 정의해야 합니다.
                      */
                      <span className="text-2xl">👤</span> 
                    )}
                  </div>
                  <span className="text-sm font-black text-white truncate">
                    {selectedCharacterData?.name}
                  </span>
                </div>
              </div>

              <div className="rounded-2xl border border-cyan-300/10 bg-cyan-500/10 p-3">
                <div className="flex items-center gap-2 mb-2">
                  <Palette className="w-4 h-4 text-cyan-200" />
                  <span className="text-[11px] text-white/60 font-bold tracking-wide">현재 배경</span>
                </div>
                {/* ✅ 수정된 배경 이미지 영역 */}
                <div
                  className="h-9 rounded-xl border border-white/10 shadow-[0_4px_0_rgba(0,0,0,0.2)] overflow-hidden relative"
                  style={{ 
                    background: !selectedBackgroundData?.imageSrc 
                      ? (selectedBackgroundData?.gradient || BACKGROUNDS[0].gradient) 
                      : 'none' 
                  }}
                >
                  {/* ✅ 현재 배경 이미지가 있다면 출력 */}
                  {selectedBackgroundData?.imageSrc && (
                    <img 
                      src={selectedBackgroundData.imageSrc} 
                      alt="현재 배경"
                      className="absolute inset-0 w-full h-full object-cover"
                    />
                  )}
                </div>

                <p className="text-sm font-black text-white mt-2 truncate">
                  {selectedBackgroundData?.name}
                </p>
              </div>
            </div>

            <div className="mt-3 rounded-2xl border border-yellow-300/15 bg-yellow-500/10 px-3 py-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Coins className="w-4 h-4 text-yellow-300" />
                <span className="text-sm text-yellow-100/80 font-bold">보유 코인</span>
              </div>
              <span className="text-lg font-black text-yellow-200">{coins}</span>
            </div>
          </div>
        </div>

        {/* 닉네임 변경권 */}
        <motion.div whileTap={{ scale: 0.985 }}>
          <div className="relative overflow-hidden rounded-[28px] p-[1px] bg-gradient-to-b from-pink-300/25 via-rose-300/10 to-white/5">
            <div className="relative rounded-[27px] border border-pink-300/10 bg-[linear-gradient(to_bottom,_rgba(236,72,153,0.13),_rgba(255,255,255,0.03))] backdrop-blur-md p-4">
              <div className="absolute inset-x-4 top-2 h-10 rounded-full bg-white/10 blur-lg" />

              <div className="relative flex items-center justify-between gap-3">
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-14 h-14 rounded-[18px] bg-gradient-to-b from-pink-500 to-rose-600 flex items-center justify-center shadow-[0_5px_0_rgba(190,24,93,0.9)]">
                    <PenLine className="w-6 h-6 text-white" />
                  </div>

                  <div className="min-w-0">
                    <p className="text-[15px] font-black text-white">닉네임 변경권</p>
                    <p className="text-[11px] text-pink-100/70 mt-0.5">한 번 구매로 이름을 새로 설정</p>
                    <div className="flex items-center gap-1 mt-2 text-yellow-300">
                      <Coins className="w-3.5 h-3.5" />
                      <span className="text-sm font-black">500</span>
                    </div>
                  </div>
                </div>

                <button
                  onClick={handleNicknameChange}
                  className="h-12 px-4 rounded-2xl text-xs font-black border border-pink-100/20 bg-gradient-to-b from-pink-500 to-rose-600 text-white shadow-[0_4px_0_rgba(190,24,93,0.9)] active:translate-y-[2px] active:shadow-[0_2px_0_rgba(190,24,93,0.9)]"
                >
                  구매
                </button>
              </div>
            </div>
          </div>
        </motion.div>

        {/* 탭 */}
        <div className="grid grid-cols-2 gap-2">
          <button
            onClick={() => setActiveTab('character')}
            className={`relative overflow-hidden h-[58px] rounded-[22px] text-sm font-black border transition-all ${
              activeTab === 'character'
                ? 'border-violet-200/20 bg-gradient-to-b from-violet-500 to-fuchsia-600 text-white shadow-[0_5px_0_rgba(91,33,182,0.92)]'
                : 'bg-white/[0.04] border-white/10 text-white/55'
            }`}
          >
            {activeTab === 'character' && (
              <div className="absolute inset-x-3 top-1 h-1/3 rounded-full bg-white/15 blur-md" />
            )}
            <span className="relative inline-flex items-center gap-2">
              <Sword className="w-4 h-4" />
              캐릭터
            </span>
          </button>

          <button
            onClick={() => setActiveTab('background')}
            className={`relative overflow-hidden h-[58px] rounded-[22px] text-sm font-black border transition-all ${
              activeTab === 'background'
                ? 'border-cyan-200/20 bg-gradient-to-b from-cyan-500 to-blue-600 text-white shadow-[0_5px_0_rgba(8,145,178,0.92)]'
                : 'bg-white/[0.04] border-white/10 text-white/55'
            }`}
          >
            {activeTab === 'background' && (
              <div className="absolute inset-x-3 top-1 h-1/3 rounded-full bg-white/15 blur-md" />
            )}
            <span className="relative inline-flex items-center gap-2">
              <Sparkles className="w-4 h-4" />
              배경
            </span>
          </button>
        </div>

        {activeTab === 'character' ? (
          <div className="space-y-3">
            {CHARACTERS.map(renderCharacterCard)}
          </div>
        ) : (
          <div className="space-y-3">
            {BACKGROUNDS.map(renderBackgroundCard)}
          </div>
        )}
      </motion.div>

      <PurchaseConfirmDialog
        open={!!purchaseTarget}
        onClose={() => setPurchaseTarget(null)}
        onConfirm={handlePurchaseConfirm}
        itemName={purchaseTarget?.item.name || ''}
        itemType={purchaseTarget?.type || 'character'}
        price={purchaseTarget?.item.price || 0}
        currentCoins={coins}
        submitting={!!pendingItemId}
      />

      <CharacterSelectDialog
        open={showNicknameDialog}
        onClose={() => setShowNicknameDialog(false)}
        isRename
      />
    </div>
  );
};

export default ShopView;