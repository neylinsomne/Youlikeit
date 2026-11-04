import { useCallback, useEffect, useRef, useState } from 'react';
import { isAbort } from '../lib/errors';

/**
 * Carga datos de la API con estados reales.
 *
 *   const { data, error, loading, refetch, setData } = useApi((signal) => api.works({ signal }), [dep1, dep2]);
 *
 * - `deps` se serializa con JSON: usa valores planos (números, strings, objetos simples).
 * - Al cambiar `deps` o llamar `refetch()` se cancela la petición anterior.
 * - `data` conserva el último valor bueno mientras se recarga (sin parpadeos).
 * - `enabled: false` no pide nada (útil cuando falta un id).
 */
export function useApi(fetcher, deps = [], { enabled = true } = {}) {
  const [nonce, setNonce] = useState(0);
  const key = JSON.stringify([deps, nonce]);
  const [result, setResult] = useState({ key: null, data: undefined, error: null });

  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    if (!enabled) return undefined;
    const ctrl = new AbortController();
    Promise.resolve()
      .then(() => fetcherRef.current(ctrl.signal))
      .then(
        (data) => {
          if (!ctrl.signal.aborted) setResult({ key, data, error: null });
        },
        (error) => {
          if (ctrl.signal.aborted || isAbort(error)) return;
          setResult((prev) => ({ key, data: prev.data, error }));
        },
      );
    return () => ctrl.abort();
  }, [key, enabled]);

  const refetch = useCallback(() => setNonce((n) => n + 1), [setNonce]);
  const setData = useCallback(
    (updater) =>
      setResult((prev) => ({
        ...prev,
        data: typeof updater === 'function' ? updater(prev.data) : updater,
      })),
    [setResult],
  );

  return {
    data: result.data,
    error: result.error,
    loading: enabled && result.key !== key,
    refetch,
    setData,
  };
}
