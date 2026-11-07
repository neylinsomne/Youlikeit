/** Item de lección → forma que acepta PATCH /api/lessons/{id}. */
export function toItemPatch(item) {
  return {
    moment_id: item.moment_id,
    in_ms: Math.round(item.in_ms),
    out_ms: Math.round(item.out_ms),
    caption: item.caption ?? '',
  };
}

export const MAX_LESSON_MS = 60000;

export function itemsDurationMs(items) {
  return (items || []).reduce((sum, it) => sum + Math.max(0, (it.out_ms ?? 0) - (it.in_ms ?? 0)), 0);
}

/** Estados en los que editar la lección la devuelve a borrador. */
export const EDIT_RESETS_STATUS = new Set(['rendered', 'approved', 'rejected']);

/** Estados en los que no conviene editar desde la UI. */
export const LOCKED_STATUS = new Set(['rendering', 'published']);
