export {};

declare global {
  interface Window {
    TossPayments?: (clientKey: string) => {
      payment: (params: { customerKey: string }) => {
        requestPayment: (params: any) => Promise<void>;
      };
    };
  }
}