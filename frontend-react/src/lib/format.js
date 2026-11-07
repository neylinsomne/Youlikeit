const LOCALE = 'es-419';

/** 366000 → "06:06.0" (mm:ss.s; los minutos pueden pasar de 59). */
export function msToClock(ms) {
  if (ms === null || ms === undefined || Number.isNaN(Number(ms))) return '—';
  const sign = ms < 0 ? '-' : '';
  const tenths = Math.round(Math.abs(ms) / 100);
  const m = Math.floor(tenths / 600);
  const s = (tenths % 600) / 10;
  return `${sign}${String(m).padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`;
}

export const secToClock = (s) => (s === null || s === undefined ? '—' : msToClock(Number(s) * 1000));

/**
 * "06:06.5" | "6:06" | "366.5" | "1:02:03.4" → milisegundos. Devuelve null si no es válido.
 * Acepta coma decimal.
 */
export function parseClock(text) {
  const t = String(text ?? '').trim().replace(',', '.');
  if (!t) return null;
  const parts = t.split(':');
  if (parts.length > 3) return null;
  let seconds = 0;
  for (let i = 0; i < parts.length; i += 1) {
    const p = parts[i];
    const isLast = i === parts.length - 1;
    if (!(isLast ? /^\d+(\.\d+)?$/ : /^\d+$/).test(p)) return null;
    if (i > 0 && Number(p) >= 60) return null;
    seconds = seconds * 60 + Number(p);
  }
  return Math.round(seconds * 1000);
}

/** 54200 → "54.2 s" */
export function fmtSeconds(ms, digits = 1) {
  if (ms === null || ms === undefined) return '—';
  return `${(ms / 1000).toFixed(digits)} s`;
}

/** 5752800 → "1 h 35 min" · 125000 → "2 min 05 s" */
export function fmtLongDuration(ms) {
  if (!ms && ms !== 0) return '—';
  const total = Math.round(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h} h ${String(m).padStart(2, '0')} min`;
  if (m) return `${m} min ${String(s).padStart(2, '0')} s`;
  return `${s} s`;
}

export function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(LOCALE, { dateStyle: 'medium', timeStyle: 'short' });
}

/** Duración entre dos fechas ISO ("2 min 05 s"), o null si falta alguna. */
export function fmtElapsed(startIso, endIso) {
  if (!startIso || !endIso) return null;
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  return Number.isFinite(ms) && ms >= 0 ? fmtLongDuration(ms) : null;
}

export function fmtGB(gb) {
  if (gb === null || gb === undefined) return '—';
  if (gb < 1) return `${Math.round(gb * 1024)} MB`;
  return `${gb.toFixed(gb < 10 ? 2 : 1)} GB`;
}

export function fmtPct(x, digits = 0) {
  if (x === null || x === undefined) return '—';
  return `${(x * 100).toFixed(digits)} %`;
}

export function fmtNumber(n) {
  if (n === null || n === undefined) return '—';
  return Number(n).toLocaleString(LOCALE);
}

/** Valor de <input type="datetime-local"> (hora local) → ISO-8601 UTC sin milisegundos. */
export function localInputToIsoUtc(value) {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

/** "emotion:fear" → ["emotion", "fear"] */
export function splitSpec(spec) {
  const [dimension, ...rest] = String(spec ?? '').split(':');
  const value = rest.join(':');
  return dimension && value ? [dimension, value] : [null, null];
}
