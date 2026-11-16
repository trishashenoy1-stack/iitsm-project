import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";

const ToastContext = createContext<(message: string) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const show = useCallback((next: string) => {
    setMessage(next);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setMessage(null), 3400);
  }, []);

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div role="status" className="pointer-events-none fixed inset-x-0 bottom-4 z-20 flex justify-center px-4">
        {message && (
          <div className="rounded-[10px] bg-paper px-3.5 py-2 text-[13px] font-medium text-on-paper">{message}</div>
        )}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
