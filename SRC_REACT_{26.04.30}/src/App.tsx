/**
 * 🏠 앱 메인 라우터 컴포넌트
 * 
 * 이 파일은 앱의 진입점으로, 전체 라우팅 구조와 전역 프로바이더를 설정합니다.
 * 
 * 📝 수정 가이드:
 * - 새 페이지 추가: Routes 내부에 새 Route 추가 (반드시 "*" 라우트 위에 추가)
 * - 보호된 라우트: ProtectedRoute 컴포넌트로 감싸서 로그인 필수 페이지 설정
 * - 전역 프로바이더 추가: QueryClientProvider 내부에 추가
 * - 토스트 위치 변경: Sonner의 position prop 수정
 * 
 * 🔗 라우트 구조:
 * - "/" : 스플래시 화면 (앱 시작)
 * - "/auth" : 로그인/회원가입 페이지
 * - "/onboarding" : 온보딩 (신체정보 입력) - 로그인 필요
 * - "/main" : 메인 대시보드 - 로그인 필요
 * - "/inbody" : 신체 분석 데이터 - 로그인 필요
 * - "/game" : 챌린지 게임 - 로그인 필요
 * - "/profile" : 프로필 설정 - 로그인 필요
 * - "*" : 404 페이지
 */

import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useAppStore } from "@/stores/appStore";
import SplashPage from "./pages/SplashPage";
import AuthPage from "./pages/AuthPage";
import OnboardingPage from "./pages/OnboardingPage";
import InBodyPage from "./pages/InBodyPage";
import HistoryPage from "./pages/HistoryPage";
import GamePage from "./pages/GamePage";
import ProfilePage from "./pages/ProfilePage";
import MissionCoinShopPage from "./pages/MissionCoinShopPage";
import WeekWalkPage from "./pages/WeekWalkPage";
import WeekWalkRewardTierPage from "./pages/WeekWalkRewardTierPage";
import NotFound from "./pages/NotFound";
import PaymentSuccessPage from "./pages/PaymentSuccessPage";
import PaymentFailPage from "./pages/PaymentFailPage";
import ProfileDetailsPage from "./pages/ProfileDetailsPage";

// React Query 클라이언트 인스턴스 생성
const queryClient = new QueryClient();

/**
 * 🔒 보호된 라우트 컴포넌트
 * 
 * 로그인하지 않은 사용자가 접근하면 /auth 페이지로 리다이렉트합니다.
 * 로그인이 필요한 페이지에서 이 컴포넌트로 감싸세요.
 */
const ProtectedRoute = ({ children }: { children: React.ReactNode }) => {
  const isLoggedIn = useAppStore((state) => state.isLoggedIn);
  
  if (!isLoggedIn) {
    return <Navigate to="/auth" replace />;
  }
  
  return <>{children}</>;
};

/**
 * 🚀 메인 앱 컴포넌트
 * 
 * 전역 프로바이더와 라우팅을 설정합니다.
 * - QueryClientProvider: React Query 상태 관리
 * - TooltipProvider: 툴팁 기능
 * - Toaster: 토스트 알림 (shadcn)
 * - Sonner: 토스트 알림 (sonner 라이브러리)
 */
const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      {/* 🔔 토스트 알림 컴포넌트들 */}
      <Toaster />
      <Sonner position="top-center" />
      
      <BrowserRouter>
        <Routes>
          {/* 🌟 공개 라우트 (로그인 불필요) */}
          <Route path="/" element={<SplashPage />} />
          <Route path="/auth" element={<AuthPage />} />
          
          {/* 🔐 보호된 라우트 (로그인 필요) */}
          <Route 
            path="/onboarding" 
            element={
              <ProtectedRoute>
                <OnboardingPage />
              </ProtectedRoute>
            } 
          />
          <Route 
            path="/main" 
            element={<Navigate to="/inbody" replace />} 
          />
          <Route 
            path="/history" 
            element={
              <ProtectedRoute>
                <HistoryPage />
              </ProtectedRoute>
            } 
          />
          <Route 
            path="/inbody" 
            element={
              <ProtectedRoute>
                <InBodyPage />
              </ProtectedRoute>
            } 
          />
          <Route 
            path="/game" 
            element={
              <ProtectedRoute>
                <GamePage />
              </ProtectedRoute>
            } 
          />
          <Route 
            path="/profile" 
            element={
              <ProtectedRoute>
                <ProfilePage />
              </ProtectedRoute>
            } 
          />
          <Route 
            path="/profile/details" 
            element={
              <ProtectedRoute>
                <ProfileDetailsPage />
              </ProtectedRoute>
            } 
          />
          <Route 
            path="/mission-coin-shop" 
            element={
              <ProtectedRoute>
                <MissionCoinShopPage />
              </ProtectedRoute>
            } 
          />
          <Route 
            path="/week-walk" 
            element={
              <ProtectedRoute>
                <WeekWalkPage />
              </ProtectedRoute>
            } 
          />
          <Route 
            path="/week-walk/rewards" 
            element={
              <ProtectedRoute>
                <WeekWalkRewardTierPage />
              </ProtectedRoute>
            } 
          />

          <Route path="/payment/success" element={<PaymentSuccessPage />} />
          <Route path="/payment/fail" element={<PaymentFailPage />} />
          
          {/* ⚠️ 새 라우트는 반드시 이 위에 추가하세요! */}
          <Route path="*" element={<NotFound />} />
        </Routes>
      </BrowserRouter>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
