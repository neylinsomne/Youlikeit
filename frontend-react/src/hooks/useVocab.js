import { useCallback, useMemo } from 'react';
import { api } from '../api/client';
import { humanize } from '../lib/labels';
import { useApi } from './useApi';

/**
 * Vocabulario controlado (GET /api/vocab, cacheado por sesión).
 * `labelOf(dim, id)` da la etiqueta en español; `has(dim, id)` valida etiquetas manuales.
 */
export function useVocab() {
  const { data, error, loading, refetch } = useApi(() => api.vocab(), []);

  const index = useMemo(() => {
    const out = {};
    for (const [dim, entries] of Object.entries(data || {})) {
      if (Array.isArray(entries)) out[dim] = new Map(entries.map((e) => [e.id, e]));
    }
    return out;
  }, [data]);

  const entryOf = useCallback((dim, id) => index[dim]?.get(id) ?? null, [index]);
  const labelOf = useCallback((dim, id) => index[dim]?.get(id)?.es || humanize(id), [index]);
  const has = useCallback((dim, id) => Boolean(index[dim]?.has(id)), [index]);
  const options = useCallback(
    (dim) =>
      (data?.[dim] || [])
        .map((e) => ({ id: e.id, label: e.es || humanize(e.id) }))
        .sort((a, b) => a.label.localeCompare(b.label, 'es')),
    [data],
  );

  return { vocab: data, error, loading, refetch, entryOf, labelOf, has, options };
}
