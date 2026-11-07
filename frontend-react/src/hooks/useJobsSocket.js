import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { api } from '../api/client';
import { applyJobEvent, isTerminal } from '../lib/jobs';
import {
  getSocketStatus,
  lastJobEvent,
  subscribeJobEvents,
  subscribeSocketStatus,
} from '../lib/jobsSocket';

const NO_JOBS = [];

/** Estado del WebSocket compartido: idle | connecting | open | closed. */
export function useSocketStatus() {
  return useSyncExternalStore(subscribeSocketStatus, getSocketStatus, getSocketStatus);
}

/**
 * Se suscribe a los eventos `studio.job` del WebSocket único.
 * `onEvent(ev)` recibe {job_id, type, status, stage, pct, detail, ts}.
 */
export function useJobsSocket(onEvent) {
  const handlerRef = useRef(onEvent);
  useEffect(() => {
    handlerRef.current = onEvent;
  });
  useEffect(() => subscribeJobEvents((ev) => handlerRef.current?.(ev)), []);
  return useSocketStatus();
}

/**
 * Mezcla en vivo los eventos del WS sobre una lista de Jobs de la API.
 * - onUnknown(ev): llegó un job que no está en la lista (o cambió de estado) → recarga.
 * - onFinish(ev): un job de la lista terminó (done/error).
 */
export function useLiveJobs(jobs, { onUnknown, onFinish } = {}) {
  const [events, setEvents] = useState({});
  const jobsRef = useRef(jobs);
  const callbacks = useRef({ onUnknown, onFinish });
  const seenStatus = useRef(new Map());
  useEffect(() => {
    jobsRef.current = jobs;
    callbacks.current = { onUnknown, onFinish };
  });

  const socket = useJobsSocket((ev) => {
    const previous = seenStatus.current.get(ev.job_id);
    seenStatus.current.set(ev.job_id, ev.status);
    const changed = previous !== ev.status;
    setEvents((prev) => ({ ...prev, [ev.job_id]: ev }));
    const known = (jobsRef.current || NO_JOBS).find((j) => j.id === ev.job_id);
    if (!known) {
      if (changed) callbacks.current.onUnknown?.(ev);
    } else if (changed && isTerminal(ev.status) && !isTerminal(known.status)) {
      callbacks.current.onFinish?.(ev);
    }
  });

  const merged = useMemo(
    () => (jobs || NO_JOBS).map((j) => applyJobEvent(j, events[j.id] ?? lastJobEvent(j.id))),
    [jobs, events],
  );
  return { jobs: merged, socket };
}

/**
 * Sigue un solo job (render, publicar) en vivo. Si el WS no está abierto, consulta
 * GET /api/jobs/{id} cada 3 s (cada 15 s como red de seguridad con el WS abierto).
 *
 *   const tracker = useJobTracker({ onFinish: (ev) => ... });
 *   tracker.track(jobDeLaApi);  tracker.job → Job en vivo o null
 */
export function useJobTracker({ onFinish, fallbackJob = null } = {}) {
  const [tracked, setTracked] = useState(null);
  const base = tracked ?? fallbackJob ?? null;
  const list = useMemo(() => (base ? [base] : NO_JOBS), [base]);

  const finishRef = useRef(onFinish);
  useEffect(() => {
    finishRef.current = onFinish;
  });
  const handleFinish = useCallback((ev) => finishRef.current?.(ev), []);

  const { jobs, socket } = useLiveJobs(list, { onFinish: handleFinish });
  const live = jobs[0] ?? null;
  const liveStatus = live?.status;
  const baseId = base?.id;

  useEffect(() => {
    if (baseId === undefined || isTerminal(liveStatus)) return undefined;
    const every = socket === 'open' ? 15000 : 3000;
    const timer = setInterval(() => {
      api.job(baseId).then(
        (job) => {
          setTracked(job);
          if (isTerminal(job.status)) {
            finishRef.current?.({
              job_id: job.id,
              type: job.type,
              status: job.status,
              detail: job.error || job.progress?.detail,
            });
          }
        },
        (err) => console.warn('[estudio] no se pudo consultar el job', baseId, err),
      );
    }, every);
    return () => clearInterval(timer);
  }, [baseId, liveStatus, socket]);

  const reset = useCallback(() => setTracked(null), []);
  return { job: live, track: setTracked, reset, socket };
}
