/**
 * Cliente de la API del Estudio (contrato: docs/architecture/STUDIO_API.md).
 *
 * - No maneja credenciales: el proxy de Vite inyecta `Authorization: Bearer $STUDIO_TOKEN`.
 * - Nunca devuelve "[]" ante un error: lanza `ApiError` con `status` y `detail` reales.
 */
const API_BASE = '/api';

export class ApiError extends Error {
  constructor(status, detail, { path = '', offline = false } = {}) {
    super(detail || `Error ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail || `Error ${status}`;
    this.path = path;
    this.offline = offline;
  }
}

function formatDetail(detail) {
  if (!detail) return '';
  if (typeof detail === 'string') return detail;
  // 422 de FastAPI: [{loc: [...], msg, type}]
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const loc = Array.isArray(d?.loc) ? d.loc.filter((p) => p !== 'body').join('.') : '';
        return loc ? `${loc}: ${d?.msg ?? ''}` : (d?.msg ?? JSON.stringify(d));
      })
      .join(' · ');
  }
  return JSON.stringify(detail);
}

async function request(method, path, { body, signal } = {}) {
  const init = { method, signal, headers: { Accept: 'application/json' } };
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
  }

  let res;
  try {
    res = await fetch(`${API_BASE}${path}`, init);
  } catch (err) {
    if (err?.name === 'AbortError') throw err;
    throw new ApiError(0, 'No se pudo conectar con el servidor del estudio.', { path, offline: true });
  }

  if (!res.ok) {
    const offline = res.headers.get('X-Studio-Proxy') === 'offline';
    let detail = res.statusText || `Error ${res.status}`;
    const text = await res.text().catch(() => '');
    if (text) {
      try {
        detail = formatDetail(JSON.parse(text).detail) || detail;
      } catch {
        detail = text.slice(0, 300); // cuerpo no JSON: lo mostramos recortado
      }
    }
    throw new ApiError(res.status, detail, { path, offline });
  }

  if (res.status === 204) return null;
  const type = res.headers.get('content-type') || '';
  return type.includes('application/json') ? res.json() : res.text();
}

function qs(params = {}) {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}

const get = (path, opts) => request('GET', path, opts);
const post = (path, body, opts) => request('POST', path, { ...opts, body });
const patch = (path, body, opts) => request('PATCH', path, { ...opts, body });
const del = (path, opts) => request('DELETE', path, opts);

// El vocabulario cambia solo con el código: se pide una vez por sesión.
let vocabPromise = null;
function getVocab() {
  if (!vocabPromise) {
    vocabPromise = get('/vocab').catch((err) => {
      vocabPromise = null;
      throw err;
    });
  }
  return vocabPromise;
}

export const api = {
  // Sistema
  health: (opts) => get('/health', opts),
  overview: (opts) => get('/overview', opts),

  // Biblioteca
  works: (opts) => get('/works', opts),
  assets: (params, opts) => get(`/assets${qs(params)}`, opts),
  mediaProviders: (opts) => get('/media/providers', opts),
  searchMedia: (body) => post('/media/search', body),
  ingest: (body) => post('/media/ingest', body),

  // Jobs
  createJob: (type, params) => post('/jobs', { type, params }),
  jobs: (params, opts) => get(`/jobs${qs(params)}`, opts),
  job: (id, opts) => get(`/jobs/${id}`, opts),

  // Momentos
  vocab: getVocab,
  moments: (params, opts) => get(`/moments${qs(params)}`, opts),
  findMoments: (params, opts) => get(`/moments/find${qs(params)}`, opts),
  moment: (id, opts) => get(`/moments/${id}`, opts),
  patchMoment: (id, body) => patch(`/moments/${id}`, body),

  // Lecciones
  createLesson: (body) => post('/lessons', body),
  lessons: (params, opts) => get(`/lessons${qs(params)}`, opts),
  lesson: (id, opts) => get(`/lessons/${id}`, opts),
  patchLesson: (id, body) => patch(`/lessons/${id}`, body),
  generateScript: (id, provider = null) => post(`/lessons/${id}/script`, { provider }),
  renderLesson: (id) => post(`/lessons/${id}/render`),

  // Revisión
  approveLesson: (id) => post(`/lessons/${id}/approve`),
  rejectLesson: (id, reason) => post(`/lessons/${id}/reject`, { reason }),
  issues: (id, opts) => get(`/lessons/${id}/issues`, opts),
  addIssue: (id, issue) => post(`/lessons/${id}/issues`, issue),
  deleteIssue: (id, issueId) => del(`/lessons/${id}/issues/${issueId}`),

  // Publicar
  tiktokAccounts: (opts) => get('/publish/tiktok/accounts', opts),
  publishTikTok: (id, openId) => post(`/lessons/${id}/publish/tiktok`, { open_id: openId }),
  youtubeStatus: (opts) => get('/publish/youtube/status', opts),
  publishYouTube: (id, body) => post(`/lessons/${id}/publish/youtube`, body),
  publications: (id, opts) => get(`/lessons/${id}/publications`, opts),
};

/** Abre el OAuth de YouTube (302 a Google; el callback vuelve a 127.0.0.1). */
export const YOUTUBE_CONNECT_URL = `${API_BASE}/publish/youtube/connect`;

/** URL de video con "cache-busting" para que el <video> no muestre un render viejo. */
export function versionedUrl(url, version) {
  if (!url) return null;
  if (!version) return url;
  return `${url}${url.includes('?') ? '&' : '?'}v=${encodeURIComponent(version)}`;
}
