import { useNavigate, useSearchParams } from 'react-router-dom';
import { XCircle } from 'lucide-react';

import { Button } from '@/components/ui/button';

const PaymentFailPage = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const code = searchParams.get('code');
  const message = searchParams.get('message');

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center px-6">
      <div className="w-full max-w-sm rounded-3xl bg-white/10 border border-white/10 p-6 text-center">
        <XCircle className="w-12 h-12 mx-auto mb-4 text-red-400" />

        <h1 className="text-lg font-bold text-white mb-2">
          결제가 완료되지 않았습니다
        </h1>

        <p className="text-sm text-white/60 leading-relaxed mb-2">
          {message || '결제가 취소되었거나 실패했습니다.'}
        </p>

        {code && <p className="text-xs text-white/30 mb-5">오류 코드: {code}</p>}

        <Button
          onClick={() => navigate('/mission-coin-shop', { replace: true })}
          className="w-full bg-cyan-600 hover:bg-cyan-700 text-white"
        >
          상점으로 돌아가기
        </Button>
      </div>
    </div>
  );
};

export default PaymentFailPage;