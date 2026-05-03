import { Crown, Medal, Shield, Star, Flame, Zap } from "lucide-react";

export const TIERS = [
  { name: "브론즈", minScore: 0, color: "from-amber-700 to-amber-900", icon: Shield, textColor: "text-amber-400" },
  { name: "실버", minScore: 500, color: "from-slate-300 to-slate-600", icon: Shield, textColor: "text-slate-200" },
  { name: "골드", minScore: 1500, color: "from-yellow-300 to-yellow-600", icon: Star, textColor: "text-yellow-300" },
  { name: "플래티넘", minScore: 3500, color: "from-cyan-300 to-cyan-600", icon: Zap, textColor: "text-cyan-300" },
  { name: "다이아", minScore: 7000, color: "from-blue-400 to-purple-500", icon: Crown, textColor: "text-blue-300" },
  { name: "마스터", minScore: 15000, color: "from-red-500 to-pink-600", icon: Flame, textColor: "text-red-300" },
] as const;

export const WEEKLY_REWARDS = [
  { label: "1위", exp: 500, coins: 300, coupons: 5, score: 200 },
  { label: "2위", exp: 350, coins: 200, coupons: 3, score: 150 },
  { label: "3위", exp: 250, coins: 150, coupons: 2, score: 120 },
  { label: "4~50위", exp: 100, coins: 50, coupons: 0, score: 80 },
  { label: "51~100위", exp: 50, coins: 30, coupons: 0, score: 50 },
  { label: "101~500위", exp: 30, coins: 0, coupons: 0, score: 30 },
  { label: "501~1000위", exp: 15, coins: 0, coupons: 0, score: 15 },
  { label: "1000위~", exp: 5, coins: 0, coupons: 0, score: 5 },
] as const;

export const SEASON_REWARDS = [
  { label: "1위", badge: "🥇 1위 훈장", coins: 1000, coupons: 20 },
  { label: "2위", badge: "🥈 2위 훈장", coins: 700, coupons: 15 },
  { label: "3위", badge: "🥉 3위 훈장", coins: 500, coupons: 10 },
  { label: "4~50위", badge: "⭐ 상위권 훈장", coins: 200, coupons: 0 },
  { label: "51~100위", badge: "🏵️ 도전자 훈장", coins: 100, coupons: 0 },
] as const;
