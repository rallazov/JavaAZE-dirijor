// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { cn } from '@/lib/utils';

export type RealmToastVariant = 'success' | 'info' | 'warn';

export interface RealmToastPayload {
  title: string;
  description?: string;
  variant?: RealmToastVariant;
}

interface RealmToastCtx {
  toast: (p: RealmToastPayload) => void;
}

const RealmToastContext = createContext<RealmToastCtx | null>(null);

export function RealmToastProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<(RealmToastPayload & { id: number }) | null>(null);
  const idSeq = useRef(0);
  const dismissTimer = useRef<number | null>(null);

  const toast = useCallback((p: RealmToastPayload) => {
    if (dismissTimer.current != null) {
      window.clearTimeout(dismissTimer.current);
      dismissTimer.current = null;
    }
    const id = ++idSeq.current;
    const next = { ...p, id, variant: p.variant ?? 'info' } as const;
    setCurrent(next);
    dismissTimer.current = window.setTimeout(() => {
      dismissTimer.current = null;
      setCurrent((t) => (t?.id === id ? null : t));
    }, 3200);
  }, []);

  useEffect(
    () => () => {
      if (dismissTimer.current != null) {
        window.clearTimeout(dismissTimer.current);
      }
    },
    []
  );

  const value = useMemo(() => ({ toast }), [toast]);

  const borderClass =
    current?.variant === 'success'
      ? 'border-realm-emerald/35 shadow-glow-emerald'
      : current?.variant === 'warn'
        ? 'border-realm-amber/35 shadow-glow-amber'
        : 'border-realm-cyan/30 shadow-glow-cyan';

  return (
    <RealmToastContext.Provider value={value}>
      {children}
      {current ? (
        <div
          role="status"
          aria-live="polite"
          className="pointer-events-none fixed bottom-[5.5rem] left-1/2 z-[100] w-[min(100vw-2rem,24rem)] -translate-x-1/2 px-4 md:bottom-8"
        >
          <div
            className={cn(
              'glass-panel rounded-xl border px-4 py-3 text-sm shadow-xl',
              borderClass
            )}
          >
            <p className="font-semibold text-zinc-50">{current.title}</p>
            {current.description ? (
              <p className="mt-1 text-xs text-realm-muted">{current.description}</p>
            ) : null}
          </div>
        </div>
      ) : null}
    </RealmToastContext.Provider>
  );
}

export function useRealmToast() {
  const ctx = useContext(RealmToastContext);
  if (!ctx) {
    throw new Error('useRealmToast must be used within RealmToastProvider');
  }
  return ctx;
}
