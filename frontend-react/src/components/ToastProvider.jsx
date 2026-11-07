import { useCallback, useMemo, useRef, useState } from 'react';
import { describeError } from '../lib/errors';
import { ToastContext } from '../lib/toastContext';
import { Icon } from './ui';

const TONES = {
  success: { icon: 'check_circle', cls: 'border-tertiary/40 text-tertiary', ttl: 5000 },
  info: { icon: 'info', cls: 'border-primary/40 text-primary', ttl: 5000 },
  warn: { icon: 'warning', cls: 'border-amber-400/40 text-amber-300', ttl: 8000 },
  error: { icon: 'error', cls: 'border-error/40 text-error', ttl: 10000 },
};

export default function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id) => setToasts((prev) => prev.filter((t) => t.id !== id)), []);

  const push = useCallback(
    (tone, message, detail) => {
      const id = nextId.current;
      nextId.current += 1;
      setToasts((prev) => [...prev.slice(-4), { id, tone, message, detail }]);
      setTimeout(() => dismiss(id), TONES[tone]?.ttl ?? 6000);
      return id;
    },
    [dismiss],
  );

  const value = useMemo(
    () => ({
      success: (message, detail) => push('success', message, detail),
      info: (message, detail) => push('info', message, detail),
      warn: (message, detail) => push('warn', message, detail),
      error: (err, context) => {
        const info = describeError(err);
        const head = context ? `${context}: ` : '';
        const status = info?.status ? ` (${info.status})` : '';
        return push('error', `${head}${info?.detail ?? 'Error desconocido'}${status}`, info?.hint);
      },
      dismiss,
    }),
    [push, dismiss],
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="fixed bottom-4 right-4 z-[70] flex flex-col gap-2 w-[min(26rem,calc(100vw-2rem))]" aria-live="polite">
        {toasts.map((t) => {
          const tone = TONES[t.tone] ?? TONES.info;
          return (
            <div
              key={t.id}
              role={t.tone === 'error' ? 'alert' : 'status'}
              className={`flex items-start gap-2 rounded-xl border bg-surface-high/95 backdrop-blur px-4 py-3 shadow-[0_8px_32px_rgba(0,0,0,0.5)] ${tone.cls}`}
            >
              <Icon name={tone.icon} className="text-base mt-px" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-bold text-on-surface break-words">{t.message}</p>
                {t.detail && <p className="text-[11px] text-on-surface-variant mt-0.5">{t.detail}</p>}
              </div>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                className="text-on-surface-variant hover:text-on-surface cursor-pointer"
                aria-label="Cerrar aviso"
              >
                <Icon name="close" className="text-sm" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
