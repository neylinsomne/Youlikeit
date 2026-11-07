export const isTerminal = (status) => status === 'done' || status === 'error';

/**
 * Aplica un evento WS {status, stage, pct, detail} a un Job del contrato.
 * Un job terminado nunca vuelve atrás (los eventos de "catchup" pueden llegar viejos).
 */
export function applyJobEvent(job, ev) {
  if (!job || !ev) return job;
  if (isTerminal(job.status) && !isTerminal(ev.status)) return job;
  const progress = job.progress || {};
  return {
    ...job,
    status: ev.status ?? job.status,
    progress: {
      ...progress,
      stage: ev.stage ?? progress.stage,
      pct: ev.pct ?? progress.pct,
      detail: ev.detail ?? progress.detail,
    },
  };
}

/** ¿El job trabaja sobre este asset? (index usa asset_ids; detect/label, asset_id) */
export function jobTouchesAsset(job, assetId) {
  const p = job?.params || {};
  return p.asset_id === assetId || (Array.isArray(p.asset_ids) && p.asset_ids.includes(assetId));
}

export function jobPct(job) {
  if (job?.status === 'done') return 100;
  const pct = Number(job?.progress?.pct);
  return Number.isFinite(pct) ? Math.max(0, Math.min(100, pct)) : null;
}
