// src/components/game/CharacterStageSprite.tsx
import { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { CHARACTER_STAGE_FRAMES, CharacterStage } from './gameData';
import { CHARACTERS } from './gameData';

interface Props {
  characterId: string | null;
  stage: CharacterStage;
  fallbackEmoji: string;
}

const CharacterStageSprite = ({ characterId, stage, fallbackEmoji }: Props) => {
  const [frameIndex, setFrameIndex] = useState(0);

  const characterConfig = CHARACTERS.find(c => c.id === characterId);
  const customScale = characterConfig?.scale ?? 1;

  // 현재 캐릭터와 단계에 맞는 프레임 배열 가져오기
  const frames = useMemo(() => {
    if (!characterId) return [];
    return CHARACTER_STAGE_FRAMES[characterId]?.[stage] || [];
  }, [characterId, stage]);

  // 팀원의 index.tsx에 있던 300ms 단위 프레임 전환 로직
  useEffect(() => {
    if (frames.length <= 1) return;

    const timer = setInterval(() => {
      setFrameIndex((prev) => (prev + 1) % frames.length);
    }, 650);

    return () => clearInterval(timer);
  }, [frames]);

  // 단계(Stage)가 바뀔 때 프레임 인덱스 초기화
  useEffect(() => {
    setFrameIndex(0);
  }, [stage]);

  return (
    <div className="relative w-48 h-48 flex items-center justify-center">
      <AnimatePresence mode="wait">
        {frames.length > 0 ? (
          <motion.img
            key={`${characterId}-${stage}`}
            src={frames[frameIndex]}
            initial={{ opacity: 0.8, scale: customScale * 0.9 }} // 팀원의 characterOpacity 로직을 AnimatePresence로 대체
            animate={{ opacity: 1, scale: customScale }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="w-full h-full object-contain drop-shadow-2xl"
            draggable={false}
          />
        ) : (
          <motion.span
            initial={{ scale: 0.8 }}
            animate={{ scale: 1 }}
            className="text-8xl drop-shadow-2xl"
          >
            {fallbackEmoji}
          </motion.span>
        )}
      </AnimatePresence>
    </div>
  );
};

export default CharacterStageSprite;