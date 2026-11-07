/**
 * Un único WebSocket a /ws compartido por toda la app, con reconexión exponencial.
 *
 * Mensajes del hub: {ts, source, stage, data}; al conectar llega {type: "catchup", events: [...]}.
 * Solo se reenvían los eventos `source: "studio.job"`, aplanados como
 * {job_id, type, status, stage, pct, detail, ts}.
 */
const MAX_DELAY_MS = 15000;
const MAX_REMEMBERED = 300;

const eventListeners = new Set();
const statusListeners = new Set();
const lastEvents = new Map(); // job_id → último evento (para jobs que se registran tarde)

let socket = null;
let status = 'idle'; // idle | connecting | open | closed
let attempt = 0;
let retryTimer = null;

function setStatus(next) {
  if (status === next) return;
  status = next;
  statusListeners.forEach((fn) => fn());
}

function hasSubscribers() {
  return eventListeners.size > 0 || statusListeners.size > 0;
}

function socketUrl() {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws`;
}

function dispatch(evt) {
  if (!evt || evt.source !== 'studio.job' || !evt.data || evt.data.job_id === undefined) return;
  const ev = { ...evt.data, ts: evt.ts };
  lastEvents.set(ev.job_id, ev);
  if (lastEvents.size > MAX_REMEMBERED) lastEvents.delete(lastEvents.keys().next().value);
  eventListeners.forEach((fn) => {
    try {
      fn(ev);
    } catch (err) {
      console.error('[estudio] error en un oyente de jobs', err);
    }
  });
}

function scheduleRetry() {
  clearTimeout(retryTimer);
  if (!hasSubscribers()) {
    setStatus('idle');
    return;
  }
  const delay = Math.min(MAX_DELAY_MS, 1000 * 2 ** attempt) + Math.floor(Math.random() * 400);
  attempt += 1;
  retryTimer = setTimeout(connect, delay);
}

function connect() {
  clearTimeout(retryTimer);
  retryTimer = null;
  if (socket || !hasSubscribers()) return;
  setStatus('connecting');
  let ws;
  try {
    ws = new WebSocket(socketUrl());
  } catch (err) {
    console.warn('[estudio] no se pudo abrir el WebSocket', err);
    setStatus('closed');
    scheduleRetry();
    return;
  }
  socket = ws;
  ws.onopen = () => {
    attempt = 0;
    setStatus('open');
  };
  ws.onmessage = (msg) => {
    let parsed;
    try {
      parsed = JSON.parse(msg.data);
    } catch {
      return; // mensaje que no es JSON: no es del hub
    }
    if (parsed?.type === 'catchup' && Array.isArray(parsed.events)) parsed.events.forEach(dispatch);
    else dispatch(parsed);
  };
  ws.onclose = () => {
    if (socket !== ws) return;
    socket = null;
    setStatus('closed');
    scheduleRetry();
  };
  // onerror siempre viene seguido de onclose, que reprograma la reconexión.
  ws.onerror = () => setStatus('closed');
}

function disconnectIfUnused() {
  if (hasSubscribers()) return;
  clearTimeout(retryTimer);
  retryTimer = null;
  if (socket) {
    const ws = socket;
    socket = null;
    ws.onclose = null;
    ws.close();
  }
  setStatus('idle');
}

export function subscribeJobEvents(fn) {
  eventListeners.add(fn);
  connect();
  return () => {
    eventListeners.delete(fn);
    setTimeout(disconnectIfUnused, 2000); // evita cerrar/abrir al navegar o en StrictMode
  };
}

export function subscribeSocketStatus(fn) {
  statusListeners.add(fn);
  connect();
  return () => {
    statusListeners.delete(fn);
    setTimeout(disconnectIfUnused, 2000);
  };
}

export function getSocketStatus() {
  return status;
}

export function lastJobEvent(jobId) {
  return lastEvents.get(jobId);
}
