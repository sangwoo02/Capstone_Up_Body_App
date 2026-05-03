/**
 * 🎫 미션 쿠폰 상점 페이지 (목업)
 */
import { useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Ticket, Check, Sparkles } from 'lucide-react';
import { useAppStore } from '@/stores/appStore';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { paymentsApi } from '@/services/api';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';

interface CoinPackage {
  id: string;
  amount: number;
  price: number;
  perUnit: number;
  popular?: boolean;
  bestValue?: boolean;
}

const PACKAGES: CoinPackage[] = [
  { id: 'pack-1', amount: 1, price: 500, perUnit: 500 },
  { id: 'pack-5', amount: 5, price: 2000, perUnit: 400 },
  { id: 'pack-10', amount: 10, price: 3800, perUnit: 380, popular: true },
  { id: 'pack-20', amount: 20, price: 7200, perUnit: 360 },
  { id: 'pack-30', amount: 30, price: 10200, perUnit: 340 },
  { id: 'pack-50', amount: 50, price: 16000, perUnit: 320, bestValue: true },
  { id: 'pack-100', amount: 100, price: 30000, perUnit: 300 },
];

const formatPrice = (price: number) => {
  return price.toLocaleString('ko-KR');
};

const getDiscount = (pkg: CoinPackage) => {
  const basePrice = pkg.amount * 500;
  if (basePrice <= pkg.price) return 0;
  return Math.round(((basePrice - pkg.price) / basePrice) * 100);
};

const MissionCoinShopPage = () => {
  const navigate = useNavigate();

  // addMissionCoins는 더 이상 구매 메인 로직으로 쓰지 않음
  const { missionCoins, refreshGameState, enqueueAchievementCelebration } = useAppStore();

  const [selectedPkg, setSelectedPkg] = useState<CoinPackage | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [purchasing, setPurchasing] = useState(false);

  const handlePurchase = (pkg: CoinPackage) => {
    setSelectedPkg(pkg);
    setShowConfirm(true);
  };

  const confirmPurchase = async () => {
    if (!selectedPkg || purchasing) return;

    try {
      setPurchasing(true);
      setShowConfirm(false);

      const order = await paymentsApi.createMissionCouponOrder({
        package_id: selectedPkg.id,
      });

      const clientKey = import.meta.env.VITE_TOSS_CLIENT_KEY;

      if (!clientKey) {
        throw new Error('VITE_TOSS_CLIENT_KEY가 설정되지 않았습니다.');
      }

      if (!window.TossPayments) {
        throw new Error('토스페이먼츠 SDK가 로드되지 않았습니다.');
      }

      const tossPayments = window.TossPayments(clientKey);

      const payment = tossPayments.payment({
        customerKey: order.customer_key,
      });

      await payment.requestPayment({
        method: 'CARD',
        amount: {
          currency: 'KRW',
          value: order.amount,
        },
        orderId: order.order_id,
        orderName: order.order_name,
        successUrl: `upbodyapp://payment/success`,
        failUrl: `upbodyapp://payment/fail`,
        customerName: 'UpBody 사용자',
        card: {
          flowMode: 'DEFAULT',
          appScheme: 'upbodyapp://',
        },
        windowTarget: 'self',
      });
    } catch (error: any) {
      console.error('토스 결제 요청 실패:', error);
      toast.error(error?.message || '결제 요청에 실패했습니다.');
      setPurchasing(false);
    }
  };

  return (
    <div className="h-full flex flex-col relative">
      {/* 배경 */}
      <div className="absolute inset-0 bg-gradient-to-b from-slate-900 via-cyan-950 to-slate-900" />

      {/* 헤더 */}
      <div className="relative z-10 px-5 pt-safe-top pb-4 flex items-center gap-3">
        <motion.button
          whileTap={{ scale: 0.95 }}
          onClick={() => navigate('/game')}
          className="p-2 rounded-xl bg-white/10 border border-white/15 text-white/70"
        >
          <ArrowLeft className="w-5 h-5" />
        </motion.button>

        <h1 className="text-lg font-bold text-white">미션 쿠폰 상점</h1>

        <div className="ml-auto flex items-center gap-1.5 bg-cyan-500/20 px-3 py-1.5 rounded-full border border-cyan-400/30">
          <Ticket className="w-4 h-4 text-cyan-400" />
          <span className="text-sm font-bold text-cyan-300">{missionCoins}</span>
        </div>
      </div>

      {/* 설명 */}
      <div className="relative z-10 px-5 mb-4">
        <div className="bg-white/5 rounded-2xl p-4 border border-white/10">
          <div className="flex items-center gap-2 mb-2">
            <Sparkles className="w-4 h-4 text-cyan-400" />
            <span className="text-sm font-semibold text-white">미션 쿠폰이란?</span>
          </div>
          <p className="text-xs text-white/50 leading-relaxed">
            하루 무료 미션 재생성 3회를 모두 사용한 뒤, 추가로 미션을 재생성하거나 새로고침할 때 사용하는 쿠폰입니다.
            미션 쿠폰 1개당 미션 1회 재생성이 가능합니다.
          </p>
        </div>
      </div>

      {/* 패키지 목록 */}
      <div className="relative z-10 flex-1   overflow-y-auto px-5 pb-[calc(env(safe-area-inset-bottom)+96px)]">
        <div className="space-y-3">
          {PACKAGES.map((pkg, index) => {
            const discount = getDiscount(pkg);

            return (
              <motion.div
                key={pkg.id}
                initial={{ opacity: 0, y: 15 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.05 }}
              >
                <button
                  onClick={() => handlePurchase(pkg)}
                  disabled={purchasing}
                  className={`w-full rounded-2xl p-4 border backdrop-blur-sm text-left transition-all active:scale-[0.98] ${
                    pkg.popular
                      ? 'bg-cyan-500/15 border-cyan-400/40 shadow-[0_0_20px_rgba(6,182,212,0.15)]'
                      : pkg.bestValue
                      ? 'bg-yellow-500/10 border-yellow-400/30 shadow-[0_0_20px_rgba(234,179,8,0.1)]'
                      : 'bg-white/5 border-white/10 hover:bg-white/10'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div
                        className={`w-12 h-12 rounded-xl flex items-center justify-center ${
                          pkg.popular
                            ? 'bg-gradient-to-br from-cyan-500 to-blue-600'
                            : pkg.bestValue
                            ? 'bg-gradient-to-br from-yellow-500 to-orange-600'
                            : 'bg-white/10'
                        }`}
                      >
                        <Ticket className="w-6 h-6 text-white" />
                      </div>

                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-base font-bold text-white">{pkg.amount}개</span>

                          {pkg.popular && (
                            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-cyan-500 text-white font-bold">
                              인기
                            </span>
                          )}

                          {pkg.bestValue && (
                            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-yellow-500 text-white font-bold">
                              최고 가성비
                            </span>
                          )}

                          {discount > 0 && (
                            <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-red-500/80 text-white font-bold">
                              -{discount}%
                            </span>
                          )}
                        </div>

                        <span className="text-[11px] text-white/40">개당 {formatPrice(pkg.perUnit)}원</span>
                      </div>
                    </div>

                    <div className="text-right">
                      <div className="text-base font-bold text-white">₩{formatPrice(pkg.price)}</div>
                      {discount > 0 && (
                        <div className="text-[11px] text-white/30 line-through">
                          ₩{formatPrice(pkg.amount * 500)}
                        </div>
                      )}
                    </div>
                  </div>
                </button>
              </motion.div>
            );
          })}
        </div>
      </div>

      {/* 구매 로딩 오버레이 */}
      {purchasing && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="absolute inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center"
        >
          <div className="text-center">
            <motion.div
              animate={{ rotate: 360 }}
              transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
              className="w-12 h-12 mx-auto mb-4 border-3 border-cyan-400/30 border-t-cyan-400 rounded-full"
            />
            <p className="text-white font-medium">결제 처리 중...</p>
            <p className="text-white/50 text-xs mt-1">토스 결제창으로 이동 중...</p>
          </div>
        </motion.div>
      )}

      {/* 구매 확인 다이얼로그 */}
      <AlertDialog open={showConfirm} onOpenChange={setShowConfirm}>
        <AlertDialogContent className="bg-slate-900 border-white/10 max-w-[340px] rounded-2xl">
          <AlertDialogHeader>
            <AlertDialogTitle className="text-white flex items-center gap-2">
              <Ticket className="w-5 h-5 text-cyan-400" />
              미션 쿠폰 구매
            </AlertDialogTitle>

            <AlertDialogDescription className="text-white/60">
              {selectedPkg && (
                <>
                  미션 쿠폰 <span className="text-cyan-300 font-bold">{selectedPkg.amount}개</span>를{' '}
                  <span className="text-white font-bold">₩{formatPrice(selectedPkg.price)}</span>에 구매하시겠습니까?
                  <br />
                  <span className="text-white/40 text-xs">결제 페이지로 이동됩니다.</span>
                </>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>

          <AlertDialogFooter className="flex-row gap-2 mt-2">
            <AlertDialogCancel className="flex-1 m-0 bg-white/10 border-white/10 text-white hover:bg-white/15 hover:text-white">
              취소
            </AlertDialogCancel>

            <AlertDialogAction
              onClick={confirmPurchase}
              className="flex-1 m-0 bg-cyan-600 hover:bg-cyan-700 text-white border-none"
            >
              <Check className="w-3.5 h-3.5 mr-1" />
              구매하기
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
};

export default MissionCoinShopPage;