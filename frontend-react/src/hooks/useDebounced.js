import { useCallback, useEffect, useRef, useState } from 'react';

/** Devuelve una función estable que ejecuta `fn` `delay` ms después de la última llamada. */
export function useDebouncedCallback(fn, delay = 800) {
  const fnRef = useRef(fn);
  const timer = useRef(null);
  useEffect(() => {
    fnRef.current = fn;
  });
  useEffect(() => () => clearTimeout(timer.current), []);
  return useCallback(
    (...args) => {
      clearTimeout(timer.current);
      timer.current = setTimeout(() => fnRef.current(...args), delay);
    },
    [delay],
  );
}

/** Valor que solo cambia cuando deja de cambiar durante `delay` ms. */
export function useDebouncedValue(value, delay = 300) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}
