import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Crown, Medal, Shield } from "lucide-react";
import { TIERS, WEEKLY_REWARDS, SEASON_REWARDS } from "./weekWalkMeta";

const WeekWalkRewardTierPage = () => {
  const navigate = useNavigate();

  return (
    <div className="h-full flex flex-col relative overflow-hidden bg-[radial-gradient(circle_at_top,_rgba(255,102,0,0.14),_transparent_22%),radial-gradient(circle_at_80%_20%,_rgba(168,85,247,0.16),_transparent_26%),linear-gradient(to_bottom,_#120b22,_#18122a_35%,_#09111f)]">
      <div className="relative z-10 px-5 pt-safe-top pb-3">
        <div className="flex items-center gap-3">
          <motion.button
            whileTap={{ scale: 0.9 }}
            onClick={() => navigate('/week-walk')}
            className="relative p-2.5 rounded-2xl border border-white/10 bg-white/5 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)] backdrop-blur-sm"
          >
            <div className="absolute inset-x-1 top-1 h-1/3 rounded-full bg-white/10 blur-sm" />
            <ArrowLeft className="relative w-5 h-5 text-white" />
          </motion.button>

          <div className="flex-1 min-w-0">
            <p className="text-[11px] tracking-[0.22em] uppercase text-orange-200/70 font-bold">경쟁전</p>
            <h1 className="text-lg font-black text-white leading-none [text-shadow:_0_2px_0_rgba(0,0,0,0.35)]">보상 및 티어</h1>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto relative z-10 px-5 pb-20">
        <div className="relative rounded-[28px] p-[1px] bg-gradient-to-b from-yellow-300/20 to-white/5">
          <div className="rounded-[27px] border border-white/5 bg-[linear-gradient(to_bottom,_rgba(255,255,255,0.05),_rgba(255,255,255,0.025))] p-4 backdrop-blur-md">
            <h3 className="text-sm font-black text-white mb-3 flex items-center gap-2">
              <div className="w-8 h-8 rounded-xl bg-gradient-to-b from-yellow-300 to-yellow-500 flex items-center justify-center shadow-[0_3px_0_rgba(133,77,14,0.9)]">
                <Crown className="w-4 h-4 text-white" />
              </div>
              시즌 보상
            </h3>

            <div className="flex items-center justify-between text-[10px] text-white/40 font-bold px-2 py-2 border-b border-white/10 mb-2">
              <span className="w-16">순위</span>
              <span className="flex-1 text-center">업적 훈장</span>
              <span className="w-16 text-center">코인</span>
              <span className="w-20 text-right">쿠폰</span>
            </div>

            <div className="space-y-2">
              {SEASON_REWARDS.map((r) => (
                <div key={r.label} className="flex items-center justify-between text-[11px] py-2.5 px-2 rounded-xl bg-white/[0.035] border border-white/5">
                  <span className="font-bold text-white/85 w-16">{r.label}</span>
                  <span className="text-purple-200 flex-1 text-center">{r.badge}</span>
                  <span className="text-yellow-300 w-16 text-center">{r.coins > 0 ? `+${r.coins}` : '-'}</span>
                  <span className="text-cyan-300 w-20 text-right">{r.coupons > 0 ? `+${r.coupons}` : '-'}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-4 relative rounded-[28px] p-[1px] bg-gradient-to-b from-orange-300/20 to-white/5">
          <div className="rounded-[27px] border border-white/5 bg-[linear-gradient(to_bottom,_rgba(255,255,255,0.05),_rgba(255,255,255,0.025))] p-4 backdrop-blur-md">
            <h3 className="text-sm font-black text-white mb-3 flex items-center gap-2">
              <div className="w-8 h-8 rounded-xl bg-gradient-to-b from-orange-400 to-red-600 flex items-center justify-center shadow-[0_3px_0_rgba(120,53,15,0.95)]">
                <Medal className="w-4 h-4 text-white" />
              </div>
              주간 보상
            </h3>

            <div className="flex items-center justify-between text-[10px] text-white/40 font-bold px-2 py-2 border-b border-white/10 mb-2">
              <span className="w-20">순위</span>
              <span className="w-20 text-center">EXP</span>
              <span className="w-16 text-center">코인</span>
              <span className="w-20 text-center">쿠폰</span>
              <span className="w-20 text-right">점수</span>
            </div>

            <div className="space-y-2">
              {WEEKLY_REWARDS.map((r) => (
                <div key={r.label} className="flex items-center justify-between text-[11px] py-2.5 px-2 rounded-xl bg-white/[0.035] border border-white/5">
                  <span className="font-bold text-white/85 w-20">{r.label}</span>
                  <span className="text-purple-200 w-20 text-center">+{r.exp}</span>
                  <span className="text-yellow-300 w-16 text-center">{r.coins > 0 ? `+${r.coins}` : '-'}</span>
                  <span className="text-cyan-300 w-20 text-center">{r.coupons > 0 ? `+${r.coupons}` : '-'}</span>
                  <span className="text-red-300 w-20 text-right">+{r.score}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-4 relative rounded-[28px] p-[1px] bg-gradient-to-b from-cyan-300/20 to-white/5">
          <div className="rounded-[27px] border border-white/5 bg-[linear-gradient(to_bottom,_rgba(255,255,255,0.05),_rgba(255,255,255,0.025))] p-4 backdrop-blur-md">
            <h3 className="text-sm font-black text-white mb-3 flex items-center gap-2">
              <div className="w-8 h-8 rounded-xl bg-gradient-to-b from-cyan-400 to-blue-500 flex items-center justify-center shadow-[0_3px_0_rgba(14,116,144,0.95)]">
                <Shield className="w-4 h-4 text-white" />
              </div>
              티어 시스템
            </h3>

            <p className="text-[10px] text-cyan-200/70 mb-3 font-semibold tracking-wide">티어와 점수는 시즌이 끝나도 유지됩니다.</p>

            <div className="grid grid-cols-3 gap-2">
              {TIERS.map((t) => {
                const Icon = t.icon;
                return (
                  <div key={t.name} className="relative overflow-hidden text-center rounded-2xl p-2.5 border bg-white/[0.03] border-white/5">
                    <div className={`relative w-9 h-9 rounded-xl bg-gradient-to-br ${t.color} flex items-center justify-center mx-auto mb-1.5 shadow-[0_4px_0_rgba(0,0,0,0.24)]`}>
                      <Icon className="w-4 h-4 text-white" />
                    </div>
                    <p className={`text-[10px] font-black ${t.textColor}`}>{t.name}</p>
                    <p className="text-[9px] text-white/40">{t.minScore}점+</p>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default WeekWalkRewardTierPage;
