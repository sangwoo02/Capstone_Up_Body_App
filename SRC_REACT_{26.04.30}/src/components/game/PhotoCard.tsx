/**
 * 🃏 포토카드 컴포넌트 - 서버 연동 버전
 *
 * 역할
 * - 서버에 저장된 game profile 기준으로 캐릭터/배경/레벨/EXP 표시
 * - 닉네임 표시 (미설정 시 "닉네임을 정해주세요!" 클릭 가능)
 * - 수동 레벨업 버튼 (EXP가 차면 활성화, 귀여운 이펙트)
 * - 보관함 버튼 (EXP 바 위 오른쪽 하단)
 * - 뱃지 표시 (포토카드 왼쪽 상단, 최대 3개)
 */

import { useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowUp, Trophy, Sparkles, Package } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import { CHARACTERS, BACKGROUNDS, ACHIEVEMENTS } from './gameData';
import CharacterSelectDialog from './CharacterSelectDialog';
import AchievementsDialog from './AchievementsDialog';
import StorageDialog from './StorageDialog';

///////////////////////////////////////0409_코드 추가 작업//////////////////////////////////////
import CharacterStageSprite from './CharacterStageSprite';
import { normalizeCharacterStage } from './gameData';
////////////////////////////////////////////////////////////////////////////////////////////////

const PhotoCard = () => {
  const {
    hasCreatedCharacter,
    selectedCharacter,
    selectedBackground,
    //0409-2수정
    ownedCharacters,
    level: globalLevel,
    ////
    exp: globalExp,
    requiredExp,
    canLevelUp,
    maxLevel,
    equippedBadges,
    levelUp,
  } = useAppStore();

  const [isLevelingUp, setIsLevelingUp] = useState(false);
  const [showNicknameDialog, setShowNicknameDialog] = useState(false);
  const [showAchievements, setShowAchievements] = useState(false);
  const [showStorage, setShowStorage] = useState(false);
  const [showLevelUpEffect, setShowLevelUpEffect] = useState(false);

  //0409_2수정
  // 1. 현재 선택된 캐릭터의 독립 레벨 찾아오기
  const currentCharacterData = useMemo(() => 
    ownedCharacters.find(c => c.id === selectedCharacter),
    [ownedCharacters, selectedCharacter]
  );

  // 캐릭터별 레벨이 있으면 그것을 쓰고, 없으면 전역 레벨 사용 (안전장치)
  const displayLevel = currentCharacterData?.level ?? globalLevel;
  ////

  const character = useMemo(
    () => CHARACTERS.find((c) => c.id === selectedCharacter),
    [selectedCharacter]
  );

  const background = useMemo(
    () => BACKGROUNDS.find((b) => b.id === selectedBackground),
    [selectedBackground]
  );

  const equippedBadgeData = useMemo(
    () =>
      equippedBadges
        .map((id) => ACHIEVEMENTS.find((a) => a.id === id))
        .filter(Boolean),
    [equippedBadges]
  );
  //0409_2수정
  const currentExp = currentCharacterData?.exp ?? globalExp;

  const expPercent =
    requiredExp > 0 ? Math.min(100, (currentExp / requiredExp) * 100) : 0;
  ////
  const isMaxLevel = displayLevel >= maxLevel;

  const handleLevelUp = async () => {
    console.log("레벨업 버튼 클릭됨!");
    console.log("상태 체크 - canLevelUp:", canLevelUp, "isMaxLevel:", isMaxLevel, "isLevelingUp:", isLevelingUp);

    if (!canLevelUp || isMaxLevel || isLevelingUp) {
      console.log("조건 불충족으로 중단됨");
      return;
    }
    
    if (!canLevelUp || isMaxLevel || isLevelingUp) return;

    try {
      setIsLevelingUp(true);
      setShowLevelUpEffect(true);

      await levelUp();

      setTimeout(() => {
        setShowLevelUpEffect(false);
      }, 1800);
    } catch (error) {
      console.error('레벨업 실패:', error);
      setShowLevelUpEffect(false);
      alert(error instanceof Error ? error.message : '레벨업에 실패했습니다.');
    } finally {
      setIsLevelingUp(false);
    }
  };

  // 1) 아직 캐릭터를 생성하지 않은 상태 → 닉네임 설정으로 대체
  if (!hasCreatedCharacter) {
    return (
      <>
        <motion.div
          whileTap={{ scale: 0.97 }}
          onClick={() => setShowNicknameDialog(true)}
          className="relative w-full aspect-[3/4] rounded-2xl overflow-hidden border-2 border-dashed border-white/20 bg-white/5 backdrop-blur-sm flex flex-col items-center justify-center cursor-pointer hover:border-violet-400/40 transition-colors"
        >
          <motion.div
            animate={{ scale: [1, 1.1, 1] }}
            transition={{ duration: 2, repeat: Infinity }}
          >
            <Sparkles className="w-12 h-12 text-violet-400/50 mb-3" />
          </motion.div>

          <p className="text-white/50 font-semibold text-sm">
            닉네임을 정해주세요!
          </p>
          <p className="text-white/30 text-xs mt-1">탭하여 닉네임 설정</p>
        </motion.div>

        <CharacterSelectDialog
          open={showNicknameDialog}
          onClose={() => setShowNicknameDialog(false)}
        />
      </>
    );
  }

  // 2) 캐릭터 생성 완료 상태
  return (
    <>
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        className="relative w-full aspect-[3/4] rounded-2xl overflow-hidden border border-white/20 shadow-[0_0_30px_rgba(139,92,246,0.3)]"
        style={{ 
          background: background?.imageSrc
          ? 'none' // 이미지가 있으면 배경색(그라데이션)은 제거
          : (background?.gradient || BACKGROUNDS[0].gradient)
        }}
      >
        {/* ✅ 2번 요청: 배경 이미지 레이어 추가 */}
        {background?.imageSrc && (
          <div className="absolute inset-0 z-0">
            <img 
              src={background.imageSrc} 
              alt={background.name}
              className="w-full h-full object-cover" // 이미지가 어색하지 않게 꽉 채움
            />
            {/* 캐릭터와 배경이 잘 어우러지도록 살짝 어둡게 처리하는 오버레이 (선택사항) */}
            <div className="absolute inset-0 bg-black/10" /> 
          </div>
        )}

        {/* 레벨업 이펙트 */}
        <AnimatePresence>
          {showLevelUpEffect && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 z-30 flex items-center justify-center"
            >
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: [0, 0.8, 0.3, 0.6, 0] }}
                transition={{ duration: 1.8 }}
                className="absolute inset-0 bg-gradient-to-b from-yellow-200/40 via-pink-200/30 to-transparent"
              />

              {[...Array(12)].map((_, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, scale: 0, x: 0, y: 0 }}
                  animate={{
                    opacity: [0, 1, 0],
                    scale: [0, 1.5, 0],
                    x: (Math.random() - 0.5) * 200,
                    y: (Math.random() - 0.5) * 200,
                  }}
                  transition={{ duration: 1.5, delay: i * 0.08 }}
                  className="absolute text-xl"
                >
                  {['✨', '⭐', '🌟', '💖', '🎀', '🌸'][i % 6]}
                </motion.div>
              ))}

              <motion.div
                initial={{ scale: 0, rotate: -10 }}
                animate={{ scale: [0, 1.3, 1], rotate: [-10, 5, 0] }}
                transition={{ duration: 0.6, delay: 0.3 }}
                className="relative z-10 text-center"
              >
                <p className="text-3xl font-black text-transparent bg-clip-text bg-gradient-to-r from-yellow-300 via-pink-300 to-violet-300 drop-shadow-lg">
                  LEVEL UP!
                </p>
                <motion.p
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.8 }}
                  className="text-sm font-bold text-white/80 mt-1"
                >
                  Lv.{displayLevel} 🎉
                </motion.p>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* 
          🏅 뱃지(훈장) 표시 영역 - 포토카드 왼쪽 상단
          최대 3개까지 표시됨
          나중에 커스텀 훈장 아이콘으로 교체 시:
          <img src={`/assets/badges/${badge.id}.png`} className="w-6 h-6" />
        */}
        {equippedBadgeData.length > 0 && (
          <div className="absolute top-3 left-3 z-10 flex gap-1">
            {equippedBadgeData.map((badge) =>
              badge ? (
                <motion.div
                  key={badge.id}
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  className="bg-black/40 backdrop-blur-sm rounded-lg px-1.5 py-1 border border-yellow-500/30"
                >
                  <span className="text-base">{badge.badge}</span>
                </motion.div>
              ) : null
            )}
          </div>
        )}

        {/* 레벨 */}
        <div className="absolute top-3 right-3 z-10 bg-black/40 backdrop-blur-sm rounded-lg px-2.5 py-1 border border-violet-500/30">
          <span className="text-xs font-bold text-violet-300">Lv.{displayLevel}</span>
        </div>
        
        {/* 캐릭터 */}{/*0409수정*/}
        <div className="absolute inset-0 flex items-center justify-center z-10">
          <motion.div
            animate={{ y: [0, -3, 0] }}
            transition={{ duration: 5.5, repeat: Infinity, ease: 'easeInOut' }}
          >
            <CharacterStageSprite
              characterId={selectedCharacter}
              stage={normalizeCharacterStage(displayLevel)} // 독립 레벨 기반 단계 계산
              fallbackEmoji={CHARACTERS.find(c => c.id === selectedCharacter)?.iconSrc || '👤'}
            />
          </motion.div>
        </div>

        {/* 하단 */}
        <div className="absolute bottom-0 left-0 right-0 z-20 bg-gradient-to-t from-black/80 via-black/40 to-transparent p-4 pt-12">
          {/* 보관함 버튼 */}
          <div className="flex justify-end mb-2">
            <motion.button
              whileTap={{ scale: 0.9 }}
              onClick={() => setShowStorage(true)}
              className="w-9 h-9 rounded-full bg-white/15 border border-white/20 flex items-center justify-center hover:bg-white/25 transition-colors"
            >
              <Package className="w-4 h-4 text-white/70" />
            </motion.button>
          </div>

          {/* EXP 바 */}
          <div className="mb-3">
            <div className="flex justify-between text-[10px] mb-1">
              <span className="text-white/50">EXP</span>
              <span className="text-yellow-300 font-semibold">
                {isMaxLevel ? 'MAX' : `${currentExp} / ${requiredExp}`}
              </span>
            </div>

            <div className="h-2 bg-black/40 rounded-full overflow-hidden border border-white/10">
              <motion.div
                className={`h-full rounded-full ${
                  canLevelUp
                    ? 'bg-gradient-to-r from-yellow-300 via-pink-400 to-violet-400'
                    : 'bg-gradient-to-r from-yellow-400 to-orange-500'
                }`}
                initial={{ width: 0 }}
                animate={{ width: `${canLevelUp ? 100 : expPercent}%` }}
                transition={{ duration: 0.8 }}
              />
            </div>
          </div>

          {/* 버튼 */}
          <div className="flex gap-2">
            <motion.button
              whileTap={canLevelUp ? { scale: 0.95 } : undefined}
              onClick={handleLevelUp}
              disabled={!canLevelUp || isMaxLevel || isLevelingUp}
              className={`flex-1 py-2 rounded-xl flex items-center justify-center gap-1.5 border text-sm font-semibold ${
                canLevelUp && !isMaxLevel
                  ? 'bg-gradient-to-r from-yellow-500 to-orange-500 border-yellow-400/50 text-white shadow-[0_0_15px_rgba(245,158,11,0.4)]'
                  : 'bg-white/10 border-white/10 text-white/30 cursor-not-allowed'
              }`}
            >
              <ArrowUp className="w-4 h-4" />
              <span>
                {isMaxLevel ? '최대 레벨' : isLevelingUp ? '처리 중...' : '레벨업'}
              </span>
              {canLevelUp && !isMaxLevel && (
                <motion.div
                  animate={{ scale: [1, 1.4, 1], rotate: [0, 15, -15, 0] }}
                  transition={{ duration: 1.2, repeat: Infinity }}
                >
                  <Sparkles className="w-3 h-3 text-yellow-200" />
                </motion.div>
              )}
            </motion.button>

            <motion.button
              whileTap={{ scale: 0.95 }}
              onClick={() => setShowAchievements(true)}
              className="flex-1 py-2 rounded-xl flex items-center justify-center gap-1.5 bg-violet-500/20 border border-violet-400/30 text-violet-300 text-sm font-semibold"
            >
              <Trophy className="w-4 h-4" />
              <span>업적</span>
            </motion.button>
          </div>
        </div>
      </motion.div>

      <AchievementsDialog
        open={showAchievements}
        onClose={() => setShowAchievements(false)}
      />

      <StorageDialog open={showStorage} onClose={() => setShowStorage(false)} />

      <CharacterSelectDialog
        open={showNicknameDialog}
        onClose={() => setShowNicknameDialog(false)}
        isRename
      />
    </>
  );
};

export default PhotoCard;