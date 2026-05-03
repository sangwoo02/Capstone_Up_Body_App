import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { CheckCircle2, Loader2, XCircle } from 'lucide-react';
import { toast } from 'sonner';

import { paymentsApi } from '@/services/api';
import { useAppStore } from '@/stores/appStore';
import { Button } from '@/components/ui/button';

const PaymentSuccessPage = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const confirmedRef = useRef(false);

  const refreshGameState = useAppStore((state) => state.refreshGameState);
  const enqueueAchievementCelebration = useAppStore(
    (state) => state.enqueueAchievementCelebration
  );

  const [status, setStatus] = useState<'loading' | 'success' | 'failed'>(
    'loading'
  );
  const [message, setMessage] = useState('결제 승인 확인 중입니다...');

  useEffect(() => {
    if (confirmedRef.current) return;
    confirmedRef.current = true;

    const confirm = async () => {
      try {
        const paymentKey = searchParams.get('paymentKey');
        const orderId = searchParams.get('orderId');
        const amount = Number(searchParams.get('amount'));

        if (!paymentKey || !orderId || !Number.isFinite(amount)) {
          throw new Error('결제 승인에 필요한 정보가 부족합니다.');
        }

        const result = await paymentsApi.confirmTossPayment({
          paymentKey,
          orderId,
          amount,
        });

        if (result?.new_achievements?.length) {
          enqueueAchievementCelebration(
            result.new_achievements.map((a) => a.achievement_code)
          );
        }

        await refreshGameState();

        setStatus('success');
        setMessage(result.message || '미션 쿠폰 구매가 완료되었습니다.');
        toast.success(result.message || '미션 쿠폰 구매가 완료되었습니다.');

        setTimeout(() => {
          navigate('/mission-coin-shop', { replace: true });
        }, 1500);
      } catch (error: any) {
        console.error('토스 결제 승인 실패:', error);
        setStatus('failed');
        setMessage(error?.message || '결제 승인 처리에 실패했습니다.');
        toast.error(error?.message || '결제 승인 처리에 실패했습니다.');
      }
    };

    confirm();
  }, [searchParams, refreshGameState, enqueueAchievementCelebration, navigate]);

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center px-6">
      <div className="w-full max-w-sm rounded-3xl bg-white/10 border border-white/10 p-6 text-center">
        {status === 'loading' && (
          <Loader2 className="w-12 h-12 mx-auto mb-4 text-cyan-400 animate-spin" />
        )}

        {status === 'success' && (
          <CheckCircle2 className="w-12 h-12 mx-auto mb-4 text-green-400" />
        )}

        {status === 'failed' && (
          <XCircle className="w-12 h-12 mx-auto mb-4 text-red-400" />
        )}

        <h1 className="text-lg font-bold text-white mb-2">
          {status === 'loading'
            ? '결제 확인 중'
            : status === 'success'
            ? '결제 완료'
            : '결제 확인 실패'}
        </h1>

        <p className="text-sm text-white/60 leading-relaxed mb-5">{message}</p>

        {status === 'failed' && (
          <Button
            onClick={() => navigate('/mission-coin-shop', { replace: true })}
            className="w-full bg-cyan-600 hover:bg-cyan-700 text-white"
          >
            상점으로 돌아가기
          </Button>
        )}
      </div>
    </div>
  );
};

export default PaymentSuccessPage;