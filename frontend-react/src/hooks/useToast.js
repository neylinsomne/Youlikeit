import { useContext } from 'react';
import { ToastContext } from '../lib/toastContext';

/** { success(msg), info(msg), error(err, contexto?) } — ver components/ToastProvider. */
export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast necesita <ToastProvider>');
  return ctx;
}
