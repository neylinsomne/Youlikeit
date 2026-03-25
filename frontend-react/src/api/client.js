const API_BASE = '/api';

let _token = null;

async function ensureToken() {
  if (_token) return _token;
  try {
    const res = await fetch(`${API_BASE}/auth/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: 'admin' }),
    });
    if (!res.ok) throw new Error(`Auth failed: ${res.status}`);
    const data = await res.json();
    _token = data.token;
    return _token;
  } catch (e) {
    console.error('[YLI] Token error:', e);
    throw e;
  }
}

async function apiFetch(path, options = {}) {
  const token = await ensureToken();
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...options.headers,
    },
  });
  if (res.status === 401) {
    _token = null;
    const newToken = await ensureToken();
    const retry = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${newToken}`,
        ...options.headers,
      },
    });
    if (!retry.ok) console.error('[YLI] Retry failed:', retry.status, url);
    return retry.json();
  }
  if (!res.ok) {
    console.error('[YLI] API error:', res.status, url);
    try { const t = await res.text(); console.error('[YLI] Body:', t); } catch {}
    return [];
  }
  return res.json();
}

// Home (no auth)
export const fetchHome = () => fetch(`${API_BASE}/home`).then(r => r.json()).catch(() => ({}));
export const fetchStatus = () => fetch(`${API_BASE}/status`).then(r => r.json()).catch(() => ({}));

// Content Bank
export const fetchMovies = (params = {}) => apiFetch(`/movies?${new URLSearchParams(params)}`);
export const fetchMangaSeries = (params = {}) => apiFetch(`/manga/series?${new URLSearchParams(params)}`);
export const fetchMangaQuotes = (params = {}) => apiFetch(`/manga/quotes?${new URLSearchParams(params)}`);
export const fetchQuotes = (params = {}) => apiFetch(`/quotes?${new URLSearchParams(params)}`);

// Music (no auth needed)
export const fetchTrendingMusic = (country = 'CO', query = '') =>
  fetch(`${API_BASE}/music/trending?country=${country}&query=${encodeURIComponent(query)}&limit=15`)
    .then(r => r.json()).catch(() => ({ songs: [] }));

// Clips
export const fetchClips = (params = {}) => apiFetch(`/clips?${new URLSearchParams(params)}`);
export const searchClips = (q) => apiFetch(`/clips/search?q=${encodeURIComponent(q)}`);

// Shorts
export const fetchShorts = (params = {}) => apiFetch(`/shorts?${new URLSearchParams(params)}`);

// Review
export const fetchReview = (status = '') => apiFetch(`/review?status=${status}`);
export const approveShort = (id) => apiFetch(`/review/${id}/approve`, { method: 'POST' });
export const rejectShort = (id, reason) => apiFetch(`/review/${id}/reject`, {
  method: 'POST', body: JSON.stringify({ reason }),
});
export const fetchIssues = (id) => apiFetch(`/review/${id}/issues`);
export const addIssue = (id, issue) => apiFetch(`/review/${id}/issues`, {
  method: 'POST', body: JSON.stringify(issue),
});

// Analytics
export const fetchAnalytics = (params = {}) => apiFetch(`/analytics?${new URLSearchParams(params)}`);
export const fetchRetention = (id) => apiFetch(`/analytics/${id}/retention`);

// Knowledge
export const fetchKnowledge = (params = {}) => apiFetch(`/knowledge?${new URLSearchParams(params)}`);

// Curriculum / Planner
export const fetchCurriculum = (status = '') => apiFetch(`/curriculum?status=${status}`);

// Pipeline
export const fetchPipelineRuns = (params = {}) => apiFetch(`/pipeline/runs?${new URLSearchParams(params)}`);
export const triggerPipeline = (pipeline, params = {}) => apiFetch('/pipeline/run', {
  method: 'POST', body: JSON.stringify({ pipeline, params }),
});

// File URL helper
export const fileUrl = (path) => `${API_BASE}/files/${path}`;
