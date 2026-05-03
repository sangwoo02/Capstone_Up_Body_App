/**
 * 🌉 React Native WebView 브릿지 훅
 *
 * RN WebView 환경에서 네이티브 앱과 통신하기 위한 공유 유틸리티입니다.
 * 각 페이지에서 중복되는 rnRequest/message handler 패턴을 하나로 통합합니다.
 */

import { useRef, useEffect, useCallback } from 'react';

export const useRnBridge = () => {
  const pendingRef = useRef(new Map<string, (msg: any) => void>());

  const isRnWebViewAvailable = useCallback(() => {
    return !!(window as any).ReactNativeWebView?.postMessage;
  }, []);

  const rnRequest = useCallback((type: string, payload: any): Promise<any> => {
    const requestId = `${Date.now()}-${Math.random().toString(16).slice(2)}`;

    return new Promise((resolve, reject) => {
      pendingRef.current.set(requestId, (msg) => {
        if (msg.ok) resolve(msg.data);
        else reject(new Error(msg.error || 'Unknown error'));
      });

      if (isRnWebViewAvailable()) {
        (window as any).ReactNativeWebView.postMessage(
          JSON.stringify({ type, requestId, payload })
        );
        return;
      }

      reject(new Error('ReactNativeWebView 연결이 없습니다. (앱(WebView)에서 실행해야 합니다)'));
    });
  }, [isRnWebViewAvailable]);

  const rnEmit = useCallback((type: string, payload: any) => {
    if (!isRnWebViewAvailable()) return false;

    (window as any).ReactNativeWebView.postMessage(
      JSON.stringify({ type, payload })
    );

    return true;
  }, [isRnWebViewAvailable]);

  // RN(WebView) -> React 메시지 수신 핸들러
  useEffect(() => {
    const handler = (event: any) => {
      try {
        const raw = event?.data;
        const msg = typeof raw === 'string' ? JSON.parse(raw) : raw;
        const requestId = msg?.requestId;
        if (!requestId) return;

        const resolver = pendingRef.current.get(requestId);
        if (!resolver) return;

        pendingRef.current.delete(requestId);
        resolver(msg);
      } catch {
        // ignore
      }
    };

    window.addEventListener('message', handler);
    document.addEventListener('message', handler as any); // RN WebView 호환

    return () => {
      window.removeEventListener('message', handler);
      document.removeEventListener('message', handler as any);
    };
  }, []);

  return { rnRequest, rnEmit, isRnWebViewAvailable };
};

/**
 * JWT 토큰 만료 확인
 */
export function isTokenExpired(token: string): boolean {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    return payload.exp * 1000 < Date.now();
  } catch {
    return true;
  }
}

/**
 * JWT 토큰 페이로드 파싱
 */
export function parseJwtPayload(token: string): any {
  try {
    const payload = token.split('.')[1];
    const base64 = payload.replace(/-/g, '+').replace(/_/g, '/');
    const json = decodeURIComponent(
      atob(base64).split('').map(c => '%' + c.charCodeAt(0).toString(16).padStart(2, '0')).join('')
    );
    return JSON.parse(json);
  } catch {
    return null;
  }
}

export const AUTO_LOGIN_KEY = 'auto_login_checked';
