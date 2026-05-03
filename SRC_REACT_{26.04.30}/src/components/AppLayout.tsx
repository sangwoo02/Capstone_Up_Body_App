/**
 * 📐 앱 레이아웃 컴포넌트
 * 
 * 앱의 기본 레이아웃 구조를 제공합니다.
 * 하단 네비게이션 바 표시 여부를 제어할 수 있습니다.
 * 
 * 📝 수정 가이드:
 * - 배경색 변경: bg-background 클래스 수정
 * - 기본 네비 표시: showNav prop 기본값 변경
 * - 스크롤 동작: overflow-y-auto 클래스 수정
 * 
 * 📌 사용 예시:
 * <AppLayout>
 *   <PageContent />
 * </AppLayout>
 * 
 * <AppLayout showNav={false}>
 *   <FullScreenContent />
 * </AppLayout>
 */

import { ReactNode } from 'react';
import BottomNav from './BottomNav';

interface AppLayoutProps {
  /** 페이지 콘텐츠 */
  children: ReactNode;
  /** 하단 네비게이션 바 표시 여부 (기본값: true) */
  showNav?: boolean;
}

const AppLayout = ({ children, showNav = true }: AppLayoutProps) => {
  return (
    <div className="h-full flex flex-col bg-background">
      {/* 📄 메인 콘텐츠 영역 - 스크롤 가능 */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {children}
      </div>
      
      {/* 🧭 하단 네비게이션 바 */}
      {showNav && <BottomNav />}
    </div>
  );
};

export default AppLayout;
