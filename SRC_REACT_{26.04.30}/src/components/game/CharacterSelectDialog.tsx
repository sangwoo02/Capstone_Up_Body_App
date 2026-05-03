/**
 * 🏷️ 닉네임 설정 다이얼로그
 *
 * - 최초 진입 시 닉네임 설정
 * - 닉네임 변경권 사용 시 닉네임 변경
 * - 닉네임은 한글/영문 2~5자
 * - 생성하기 버튼 클릭 시 확인 팝업 전에 서버 중복 검사
 * - 중복 닉네임이면 입력창 아래 에러 표시
 * - 한글 조합(IME) 입력 깨짐 방지
 */

import { useEffect, useMemo, useState } from 'react';
import type { ChangeEvent, CompositionEvent } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import { gameApi } from '@/services/api';
import { toast } from 'sonner';

interface CharacterSelectDialogProps {
  open: boolean;
  onClose: () => void;
  /** 닉네임 변경 모드 (상점에서 변경권 사용 시) */
  isRename?: boolean;
}

const GAME_NICKNAME_REGEX = /^[A-Za-z가-힣]{2,5}$/;

const sanitizeNickname = (value: string) => {
  return value.replace(/[^A-Za-z가-힣]/g, '').slice(0, 5);
};

const CharacterSelectDialog = ({
  open,
  onClose,
  isRename = false,
}: CharacterSelectDialogProps) => {
  const {
    hasCreatedCharacter,
    refreshGameState,
    nickname,
    enqueueAchievementCelebration,
  } = useAppStore();

  const [inputValue, setInputValue] = useState('');
  const [showConfirm, setShowConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [checkingDuplicate, setCheckingDuplicate] = useState(false);
  const [isComposing, setIsComposing] = useState(false);
  const [fieldError, setFieldError] = useState('');

  const trimmedValue = useMemo(() => inputValue.trim(), [inputValue]);
  const sanitizedLength = useMemo(
    () => sanitizeNickname(inputValue).trim().length,
    [inputValue]
  );
  const isValid = useMemo(
    () => GAME_NICKNAME_REGEX.test(trimmedValue),
    [trimmedValue]
  );

  useEffect(() => {
    if (!open) return;

    setInputValue(isRename && nickname ? nickname : '');
    setShowConfirm(false);
    setSubmitting(false);
    setCheckingDuplicate(false);
    setIsComposing(false);
    setFieldError('');
  }, [open, isRename, nickname]);

  const handleCreate = async () => {
    const sanitized = sanitizeNickname(inputValue).trim();

    setInputValue(sanitized);
    setFieldError('');

    if (!GAME_NICKNAME_REGEX.test(sanitized)) {
      setFieldError('게임 닉네임은 한글/영문 2~5글자로 입력해주세요.');
      return;
    }

    try {
      setCheckingDuplicate(true);

      const result = await gameApi.checkGameNicknameAvailability({
        game_nickname: sanitized,
      });

      if (!result.available) {
        setFieldError(result.message || '중복된 닉네임입니다.');
        return;
      }

      setShowConfirm(true);
    } catch (error: any) {
      console.error('닉네임 중복 확인 실패:', error);

      const message = error?.message || '닉네임 중복 확인에 실패했습니다.';

      if (
        message.includes('중복된 닉네임') ||
        message.includes('이미 사용 중') ||
        message.includes('2글자') ||
        message.includes('5글자') ||
        message.includes('한글') ||
        message.includes('영문')
      ) {
        setFieldError(message);
        return;
      }

      toast.error(message);
    } finally {
      setCheckingDuplicate(false);
    }
  };

  const handleConfirm = async () => {
    if (submitting) return;

    const sanitized = sanitizeNickname(inputValue).trim();

    if (!GAME_NICKNAME_REGEX.test(sanitized)) {
      setFieldError('게임 닉네임은 한글/영문 2~5글자로 입력해주세요.');
      setShowConfirm(false);
      return;
    }

    try {
      setSubmitting(true);
      setFieldError('');

      if (!isRename && !hasCreatedCharacter) {
        await gameApi.initializeCharacter({
          character_id: 'char-default',
          background_id: 'bg-default',
        });
      }

      const result = await gameApi.updateGameNickname({
        game_nickname: sanitized,
        consume_coins: isRename,
      });

      if (result?.new_achievements?.length) {
        enqueueAchievementCelebration(
          result.new_achievements.map((a) => a.achievement_code)
        );
      }

      await refreshGameState();

      toast.success(
        isRename
          ? `게임 닉네임이 변경되었습니다!${
              result.charged_coins > 0 ? ` (-${result.charged_coins}코인)` : ''
            }`
          : '게임 닉네임이 설정되었습니다!'
      );

      setShowConfirm(false);
      onClose();
    } catch (error: any) {
      console.error('닉네임 설정 실패:', error);

      const message = error?.message || '닉네임 설정에 실패했습니다.';

      if (
        message.includes('중복된 닉네임') ||
        message.includes('이미 사용 중') ||
        message.includes('2글자') ||
        message.includes('5글자') ||
        message.includes('한글') ||
        message.includes('영문')
      ) {
        setFieldError(message);
        setShowConfirm(false);
        return;
      }

      toast.error(message);
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center p-4"
      >
        <div
          className="absolute inset-0 bg-black/70 backdrop-blur-sm"
          onClick={() => {
            if (!submitting && !checkingDuplicate) onClose();
          }}
        />

        <motion.div
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.9, opacity: 0 }}
          className="relative w-full max-w-[340px] bg-slate-900 rounded-2xl border border-violet-500/30 shadow-[0_0_40px_rgba(139,92,246,0.3)]"
        >
          <div className="p-4 border-b border-white/10 flex items-center justify-between">
            <h2 className="text-lg font-bold text-white">
              {isRename ? '닉네임 변경' : '닉네임 설정'}
            </h2>

            <button
              onClick={onClose}
              disabled={submitting || checkingDuplicate}
              className="p-1 rounded-lg hover:bg-white/10 disabled:opacity-50"
            >
              <X className="w-5 h-5 text-white/60" />
            </button>
          </div>

          <div className="p-5 space-y-4">
            <div>
              <label className="text-xs text-white/50 mb-1.5 block">
                닉네임 (한글/영문 2~5자)
              </label>

              <input
                type="text"
                value={inputValue}
                onCompositionStart={() => setIsComposing(true)}
                onCompositionEnd={(e: CompositionEvent<HTMLInputElement>) => {
                  setIsComposing(false);
                  setInputValue(sanitizeNickname(e.currentTarget.value));
                }}
                onChange={(e: ChangeEvent<HTMLInputElement>) => {
                  const raw = e.target.value;
                  setFieldError('');

                  if (isComposing) {
                    setInputValue(raw);
                    return;
                  }

                  setInputValue(sanitizeNickname(raw));
                }}
                onBlur={() => {
                  setInputValue((prev) => sanitizeNickname(prev));
                }}
                placeholder="닉네임을 입력하세요"
                className={`w-full px-4 py-3 rounded-xl bg-white/10 border text-white placeholder:text-white/30 text-sm focus:outline-none focus:ring-1 ${
                  fieldError
                    ? 'border-red-400/60 focus:border-red-400/70 focus:ring-red-400/30'
                    : 'border-white/20 focus:border-violet-400/50 focus:ring-violet-400/30'
                }`}
                disabled={submitting || checkingDuplicate}
                autoFocus
              />

              <p className="text-[10px] text-white/30 mt-1">
                {sanitizedLength}/5 글자
              </p>

              <p className="text-[10px] text-white/40 mt-1">
                한글/영문만 사용 가능하며, 공백·숫자·특수문자는 사용할 수 없어요.
              </p>

              {fieldError ? (
                <p className="text-[11px] text-red-300 mt-1">{fieldError}</p>
              ) : null}
            </div>

            <button
              onClick={handleCreate}
              disabled={!isValid || submitting || checkingDuplicate}
              className={`w-full py-3 rounded-xl text-sm font-semibold border transition-all ${
                isValid && !checkingDuplicate
                  ? 'bg-gradient-to-r from-violet-600 to-purple-600 text-white border-white/20 shadow-[0_0_20px_rgba(139,92,246,0.4)]'
                  : 'bg-white/5 text-white/25 border-white/10 cursor-not-allowed'
              }`}
            >
              {checkingDuplicate
                ? '중복 확인 중...'
                : submitting
                  ? '처리 중...'
                  : isRename
                    ? '변경하기'
                    : '생성하기'}
            </button>
          </div>
        </motion.div>

        <AnimatePresence>
          {showConfirm && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 z-[60] flex items-center justify-center p-6"
            >
              <div
                className="absolute inset-0 bg-black/50"
                onClick={() => {
                  if (!submitting) setShowConfirm(false);
                }}
              />

              <motion.div
                initial={{ scale: 0.9 }}
                animate={{ scale: 1 }}
                exit={{ scale: 0.9 }}
                className="relative bg-slate-900 rounded-2xl border border-violet-500/30 p-5 w-full max-w-[300px]"
              >
                <h3 className="font-bold text-white text-center mb-3">
                  "{sanitizeNickname(trimmedValue)}"
                </h3>

                <p className="text-sm text-white/70 text-center mb-4">
                  이 닉네임으로 {isRename ? '변경' : '선택'}하시겠습니까?
                </p>

                <div className="flex gap-2">
                  <button
                    onClick={() => setShowConfirm(false)}
                    disabled={submitting}
                    className="flex-1 py-2.5 rounded-xl bg-white/10 border border-white/10 text-white/70 text-sm font-medium disabled:opacity-50"
                  >
                    아니요
                  </button>

                  <button
                    onClick={handleConfirm}
                    disabled={submitting}
                    className="flex-1 py-2.5 rounded-xl bg-gradient-to-r from-violet-600 to-purple-600 text-white text-sm font-semibold border border-white/20 disabled:opacity-60"
                  >
                    {submitting ? '저장 중...' : '예'}
                  </button>
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </AnimatePresence>
  );
};

export default CharacterSelectDialog;