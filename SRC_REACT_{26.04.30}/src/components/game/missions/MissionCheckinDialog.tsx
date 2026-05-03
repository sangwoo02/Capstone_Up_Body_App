/**
 * 📝 컨디션 기록 다이얼로그 (C1_HEALTH_CHECKIN)
 * 연필 아이콘 → 팝업 → minLength 이상 작성 → 완료
 */
import { useState } from "react";
import { motion } from "framer-motion";
import { PenLine, CheckCircle2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";

interface MissionCheckinDialogProps {
  onComplete: (text: string) => void;
  completed?: boolean;
  minLength?: number;
  title?: string;
}

type CheckinValidationResult = {
  isValid: boolean;
  reason: string;
  detail: {
    trimmedLength: number;
    hangulSyllables: number;
    jamoChars: number;
    minHangulSyllables: number;
    koreanWordCount: number;
    healthContextCount: number;
    temporalKeywordCount: number;
    endingClueCount: number;
    naturalClueScore: number;
    suspiciousRandomWords: boolean;
    junkMarkerCount: number;
    jamoNoiseChars: number;
    randomNoiseWordCount: number;
    randomNoiseRatio: number;
  };
};

// 오늘/어제 같은 시간 단어는 문장 자연성 힌트로만 보고,
// 건강/컨디션 맥락으로는 인정하지 않는다.
const TEMPORAL_KEYWORDS = [
  "오늘", "어제", "아침", "점심", "저녁", "오후", "밤", "하루", "평소", "방금",
];

const HEALTH_CONTEXT_KEYWORDS = [
  "몸", "컨디션", "기분", "상태", "건강", "체력", "활력",
  "피곤", "피로", "힘들", "지치", "졸리", "무기력", "나른",
  "무겁", "가볍", "상쾌", "개운", "괜찮", "좋", "나쁘",
  "아프", "아픔", "아팠", "아파", "아픈", "아프고", "아프네", "아프다",
  "불편", "붓", "통증", "쑤시", "뻐근", "어지럽", "두통", "소화", "체함", "메스껍",
  "운동", "걷", "걸음", "산책", "스트레칭", "활동", "칼로리", "땀", "심박", "숨",
  "수면", "잠", "휴식", "회복", "스트레스", "식사", "밥", "물", "마심", "먹음",
  "마음", "멘탈", "우울", "불안", "짜증", "화남", "행복", "편안", "답답", "속상",
  "이겨냈", "버텼", "견뎠", "극복", "나아졌", "좋아졌", "회복됐",
  "허리", "어깨", "다리", "무릎", "팔", "목", "머리", "속", "배", "근육",
];

const JUNK_MARKERS = [
  "ㅋㅋ", "ㅎㅎ", "ㅜㅜ", "ㅠㅠ", "말이되", "어이없", "아무말", "테스트",
  "뭐지", "뭐임", "뭔소리", "대충", "푸엣", "우엑", "으엑", "asdf", "qwer",
];

const NATURAL_WORD_ENDINGS = [
  "어요", "아요", "예요", "이에요", "해요", "네요", "습니다", "합니다",
  "했어요", "였어요", "었어요", "았어요", "같아요", "느껴져요", "느꼈어요",
  "좋았어요", "힘들었어요", "피곤했어요", "괜찮았어요",
  "좋음", "나쁨", "피곤함", "힘듦", "지침", "졸림", "괜찮음", "불편함", "가벼움", "무거움", "개운함",
  "했음", "있음", "없음", "마심", "먹음", "느낌", "완료", "함",
  "했다", "었다", "았다", "팠다", "한다", "좋다", "나쁘다", "아프다", "아팠다", "이겨냈다", "버텼다", "피곤하다", "힘들다", "괜찮다", "같다", "중",
];

const CONNECTIVE_ENDINGS = [
  "은", "는", "이", "가", "을", "를", "에", "도", "만", "로", "으로",
  "에서", "하고", "해서", "고", "지만", "더니", "니까", "라서", "면서", "는데", "보다",
];

// 정상 메모에서 자주 쓰이는 연결/감탄 표현은 랜덤 단어로 보지 않는다.
const COMMON_BRIDGE_WORDS = [
  "정말", "진짜", "하지만", "그래도", "그리고", "조금", "많이", "너무", "약간",
  "이게", "이건", "나는", "나도", "나니까", "이것이", "휴", "오늘은", "오늘도",
  "그래서", "다행히", "아직", "계속", "다시", "좀", "더", "잘", "못",
];

const normalizeCheckinText = (value: string) =>
  value.trim().replace(/\s+/g, " ");

const countKeywordHits = (normalized: string, keywords: string[]) =>
  keywords.reduce(
    (count, keyword) => count + (normalized.includes(keyword) ? 1 : 0),
    0
  );

const getEndingClueCount = (words: string[]) => {
  let count = 0;

  for (const word of words) {
    const koreanOnly = word.replace(/[^가-힣]/g, "");
    if (koreanOnly.length < 2) continue;

    if (NATURAL_WORD_ENDINGS.some((ending) => koreanOnly.endsWith(ending))) {
      count += 1;
      continue;
    }

    if (
      koreanOnly.length >= 3 &&
      CONNECTIVE_ENDINGS.some((ending) => koreanOnly.endsWith(ending))
    ) {
      count += 1;
    }
  }

  return count;
};

const hasAnyKeyword = (word: string, keywords: string[]) =>
  keywords.some((keyword) => word.includes(keyword));

const hasNaturalWordClue = (word: string) => {
  if (word.length < 4) return true;
  if (COMMON_BRIDGE_WORDS.includes(word)) return true;
  if (hasAnyKeyword(word, HEALTH_CONTEXT_KEYWORDS)) return true;
  if (hasAnyKeyword(word, TEMPORAL_KEYWORDS)) return true;
  if (NATURAL_WORD_ENDINGS.some((ending) => word.endsWith(ending))) return true;
  if (CONNECTIVE_ENDINGS.some((ending) => word.endsWith(ending))) return true;
  return false;
};

const validateCheckinText = (
  value: string,
  minLength: number
): CheckinValidationResult => {
  const requiredLength = Math.max(Number(minLength) || 15, 1);
  const trimmed = value.trim();
  const normalized = normalizeCheckinText(value);
  const compact = normalized.replace(/\s/g, "");

  const hangulSyllables = (normalized.match(/[가-힣]/g) || []).length;
  const jamoChars = (normalized.match(/[ㄱ-ㅎㅏ-ㅣ]/g) || []).length;
  const totalKoreanChars = hangulSyllables + jamoChars;
  const minHangulSyllables = Math.max(8, Math.ceil(requiredLength * 0.45));
  const hangulRatio =
    totalKoreanChars > 0 ? hangulSyllables / totalKoreanChars : 0;

  const words = normalized.split(/\s+/).filter(Boolean);
  const koreanWords = words
    .map((word) => word.replace(/[^가-힣]/g, ""))
    .filter((word) => word.length >= 2);

  const hasSentenceLikeStructure =
    koreanWords.length >= 2 ||
    hangulSyllables >= Math.max(10, Math.ceil(requiredLength * 0.65));

  const repeatedSingleChar = /(.)\1{3,}/u.test(compact);
  const repeatedJamo = /([ㄱ-ㅎㅏ-ㅣ])\1{2,}/u.test(compact);
  const repeatedKoreanChunk = /([가-힣]{1,3})\1{2,}/u.test(compact);

  const wordCounts = new Map<string, number>();
  for (const word of koreanWords) {
    wordCounts.set(word, (wordCounts.get(word) || 0) + 1);
  }
  const repeatedWordCount = Math.max(0, ...Array.from(wordCounts.values()));

  const hasRepeatedPattern =
    repeatedSingleChar || repeatedJamo || repeatedKoreanChunk || repeatedWordCount >= 3;

  const uniqueHangulCount = new Set(compact.match(/[가-힣]/g) || []).size;
  const hasLowVariety = hangulSyllables >= 8 && uniqueHangulCount <= 3;

  const meaningfulChars = (compact.match(/[가-힣A-Za-z0-9]/g) || []).length;
  const meaningfulRatio = compact.length > 0 ? meaningfulChars / compact.length : 0;
  const hasTooManySymbols = compact.length >= 6 && meaningfulRatio < 0.65;

  const healthContextCount = countKeywordHits(normalized, HEALTH_CONTEXT_KEYWORDS);
  const temporalKeywordCount = countKeywordHits(normalized, TEMPORAL_KEYWORDS);
  const junkMarkerCount = countKeywordHits(normalized.toLowerCase(), JUNK_MARKERS);
  const endingClueCount = getEndingClueCount(words);
  const hasNaturalSentenceEnding = NATURAL_WORD_ENDINGS.some((ending) =>
    normalized.endsWith(ending)
  );
  const naturalClueScore =
    healthContextCount * 3 +
    temporalKeywordCount +
    endingClueCount +
    (hasNaturalSentenceEnding ? 2 : 0);

  const suspiciousRandomWords =
    koreanWords.length >= 4 &&
    healthContextCount === 0 &&
    endingClueCount <= 2;

  const allShortDetachedWords =
    koreanWords.length >= 5 &&
    koreanWords.every((word) => word.length <= 3) &&
    healthContextCount === 0 &&
    endingClueCount <= 2;

  // ㅋㅋ/ㅎㅎ/ㅜㅜ/ㅠㅠ 정도는 감정 표현으로 허용하되,
  // 그 외 자모가 길게 섞이면 랜덤 입력으로 본다.
  const compactWithoutBenignJamo = compact.replace(/(ㅋ{2,}|ㅎ{2,}|ㅜ{2,}|ㅠ{2,})/g, "");
  const jamoNoiseChars = (compactWithoutBenignJamo.match(/[ㄱ-ㅎㅏ-ㅣ]/g) || []).length;

  const randomNoiseWords = koreanWords.filter(
    (word) => word.length >= 4 && !hasNaturalWordClue(word)
  );
  const randomNoiseWordCount = randomNoiseWords.length;
  const randomNoiseChars =
    randomNoiseWords.reduce((sum, word) => sum + word.length, 0) + jamoNoiseChars;
  const randomNoiseRatio =
    totalKoreanChars > 0 ? randomNoiseChars / totalKoreanChars : 0;

  const detail = {
    trimmedLength: trimmed.length,
    hangulSyllables,
    jamoChars,
    minHangulSyllables,
    koreanWordCount: koreanWords.length,
    healthContextCount,
    temporalKeywordCount,
    endingClueCount,
    naturalClueScore,
    suspiciousRandomWords: suspiciousRandomWords || allShortDetachedWords,
    junkMarkerCount,
    jamoNoiseChars,
    randomNoiseWordCount,
    randomNoiseRatio: Number(randomNoiseRatio.toFixed(3)),
  };

  if (trimmed.length < requiredLength) {
    return {
      isValid: false,
      reason: `${requiredLength}자 이상 작성해주세요.`,
      detail,
    };
  }

  if (hangulSyllables < minHangulSyllables) {
    return {
      isValid: false,
      reason: `자음/모음이 아닌 완성형 한글을 ${minHangulSyllables}자 이상 포함해주세요.`,
      detail,
    };
  }

  if (jamoChars > 0 && hangulRatio < 0.8) {
    return {
      isValid: false,
      reason: "ㄱ, ㅏ 같은 자모만 많이 입력하지 말고 완성된 문장으로 작성해주세요.",
      detail,
    };
  }

  if (hasRepeatedPattern) {
    return {
      isValid: false,
      reason: "같은 글자나 짧은 단어를 반복하지 말고 오늘 상태를 구체적으로 적어주세요.",
      detail,
    };
  }

  if (hasLowVariety) {
    return {
      isValid: false,
      reason: "비슷한 글자만 반복된 기록은 완료할 수 없어요.",
      detail,
    };
  }

  if (hasTooManySymbols) {
    return {
      isValid: false,
      reason: "기호나 숫자보다 실제 문장 중심으로 작성해주세요.",
      detail,
    };
  }

  if (!hasSentenceLikeStructure) {
    return {
      isValid: false,
      reason: "단어 하나만 쓰기보다 오늘 컨디션을 짧은 문장으로 적어주세요.",
      detail,
    };
  }

  if (jamoNoiseChars >= 3) {
    return {
      isValid: false,
      reason: "자음/모음이 섞인 무작위 입력은 줄이고 오늘 상태를 문장으로 적어주세요.",
      detail,
    };
  }

  if (randomNoiseWordCount >= 3 && randomNoiseRatio >= 0.25) {
    return {
      isValid: false,
      reason: "의미 없는 단어를 길게 붙이지 말고 오늘의 몸 상태나 기분을 중심으로 적어주세요.",
      detail,
    };
  }

  if (randomNoiseRatio >= 0.45) {
    return {
      isValid: false,
      reason: "기록 대부분이 무작위 단어처럼 보여요. 컨디션이나 활동 내용을 더 구체적으로 적어주세요.",
      detail,
    };
  }

  // '오늘', '정말', '말이 되는 건가'처럼 자연스러워 보여도
  // 건강/컨디션 맥락이 없으면 기록형 미션 완료로 인정하지 않는다.
  if (healthContextCount === 0) {
    return {
      isValid: false,
      reason: "몸 상태, 기분, 운동, 수면 등 건강 관련 내용을 포함해주세요.",
      detail,
    };
  }

  // 장난/테스트성 표현은 건강/기분 맥락이 전혀 없을 때만 차단한다.
  // 예: "아팠다 ㅋㅋ 그래도 괜찮다"처럼 실제 상태를 적은 문장은 허용한다.
  if (junkMarkerCount > 0 && healthContextCount === 0) {
    return {
      isValid: false,
      reason: "장난성 표현보다 오늘의 몸 상태나 활동 내용을 적어주세요.",
      detail,
    };
  }

  if (suspiciousRandomWords || allShortDetachedWords || naturalClueScore < 4) {
    return {
      isValid: false,
      reason: "컨디션이나 몸 상태를 알 수 있는 자연스러운 문장으로 적어주세요.",
      detail,
    };
  }

  return {
    isValid: true,
    reason: "완료할 수 있는 기록이에요.",
    detail,
  };
};

const MissionCheckinDialog = ({
  onComplete,
  completed,
  minLength = 15,
  title = "기록",
}: MissionCheckinDialogProps) => {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");

  const requiredLength = Math.max(minLength, 1);
  const trimmed = text.trim();
  const validation = validateCheckinText(text, requiredLength);
  const isValid = validation.isValid;
  const { hangulSyllables, minHangulSyllables } = validation.detail;

  if (completed) {
    return (
      <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-500/20 border border-emerald-400/30 text-emerald-300 text-[11px] font-semibold">
        <CheckCircle2 className="w-3 h-3" />
        기록완료
      </div>
    );
  }

  return (
    <>
      <motion.button
        whileTap={{ scale: 0.95 }}
        onClick={() => setOpen(true)}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-500/20 border border-violet-400/30 text-violet-300 text-[11px] font-semibold"
      >
        <PenLine className="w-3 h-3" />
        기록하기
      </motion.button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="bg-slate-900 border-white/10 max-w-[360px] rounded-2xl">
          <DialogHeader>
            <DialogTitle className="text-white text-base">{title}</DialogTitle>
          </DialogHeader>

          <Textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={`예시) 오늘은 산책을 해서 몸이 조금 가벼웠고 오후에는 피로감이 있었어요.\n온점 없이 작성해도 되지만 자음/모음 반복이나 장난성 문장은 완료되지 않아요. (${requiredLength}자 이상)`}
            className="bg-white/5 border-white/10 text-white placeholder:text-white/30 min-h-[120px] resize-none"
          />

          <div className="mt-2 flex items-start justify-between gap-3">
            <p
              className={`min-w-0 flex-1 max-w-[52%] text-[10px] leading-relaxed whitespace-normal break-keep ${
                isValid ? "text-emerald-400" : "text-amber-300/80"
              }`}
            >
              {validation.reason}
            </p>
            <p
              className={`shrink-0 max-w-[46%] text-[10px] leading-relaxed text-right whitespace-normal ${
                isValid ? "text-emerald-400" : "text-white/35"
              }`}
            >
              {trimmed.length}/{requiredLength}자 · 완성형 {hangulSyllables}/{minHangulSyllables}자
            </p>
          </div>

          <DialogFooter className="flex-row gap-2">
            <Button
              variant="ghost"
              onClick={() => setOpen(false)}
              className="flex-1 text-white/60 hover:text-white hover:bg-white/10"
            >
              취소
            </Button>

            <Button
              disabled={!isValid}
              onClick={() => {
                setOpen(false);
                onComplete(text.trim());
                setText("");
              }}
              className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white disabled:opacity-30"
            >
              완료
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
};

export default MissionCheckinDialog;
