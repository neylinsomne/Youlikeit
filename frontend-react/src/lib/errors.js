/** Convierte cualquier error en { status, detail, hint } legible en español. */
export function describeError(err) {
  if (!err) return null;
  const status = typeof err.status === 'number' ? err.status : null;
  const detail = err.detail || err.message || String(err);
  let hint = null;
  if (err.offline || status === 0) {
    hint = 'Inicia la API con `ylk studio` (o scripts/ops/studio.ps1) y vuelve a intentar.';
  } else if (status === 401) {
    hint = 'Token rechazado: revisa STUDIO_TOKEN en el .env de la raíz y reinicia `npm run dev`.';
  } else if (status === 403) {
    hint = 'Abre el estudio desde http://127.0.0.1:5180.';
  } else if (status === 502) {
    hint = 'Falló un servicio externo (puente web, TikTok, YouTube o IA).';
  }
  return { status, detail, hint };
}

/** Texto corto para toasts: "detalle (409)". */
export function errorText(err) {
  const d = describeError(err);
  if (!d) return '';
  return d.status ? `${d.detail} (${d.status})` : d.detail;
}

export const isAbort = (err) => err?.name === 'AbortError';
