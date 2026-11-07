import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import JobRow from '../components/JobRow';
import { Button, Card, EmptyState, ErrorBanner, LoadingBlock, PageHeader, Tabs } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useDebouncedCallback } from '../hooks/useDebounced';
import { useLiveJobs } from '../hooks/useJobsSocket';
import { JOB_STATUS, JOB_TYPE } from '../lib/labels';
import { selectCls } from '../lib/styles';

const NO_ITEMS = [];
const STATUS_TABS = [{ id: '', label: 'Todos' }, ...Object.entries(JOB_STATUS).map(([id, s]) => ({ id, label: s.label }))];

export default function Trabajos() {
  const [sp, setSp] = useSearchParams();
  const status = sp.get('status') ?? '';
  const type = sp.get('type') ?? '';
  const limit = Number(sp.get('limit')) || 50;
  const [expanded, setExpanded] = useState(() => new Set());

  const jobs = useApi((signal) => api.jobs({ status, limit }, { signal }), [status, limit]);
  const refresh = useDebouncedCallback(jobs.refetch, 1000);
  const { jobs: live, socket } = useLiveJobs(jobs.data?.items ?? NO_ITEMS, { onUnknown: refresh, onFinish: refresh });

  // Con filtro de estado, un job que cambia de estado puede dejar de pertenecer a la lista.
  const visible = live.filter((j) => (!type || j.type === type) && (!status || j.status === status));

  const setParam = (key, value) => {
    const next = new URLSearchParams(sp);
    if (value) next.set(key, value);
    else next.delete(key);
    setSp(next, { replace: true });
  };

  const toggle = (id) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <>
      <PageHeader
        title="Trabajos"
        subtitle="Una sola cola para red y GPU: indexar, detectar, etiquetar, renderizar y publicar. Se actualiza en vivo por WebSocket."
        actions={
          <Button variant="ghost" icon="refresh" loading={jobs.loading} onClick={jobs.refetch}>
            Actualizar
          </Button>
        }
      />

      <div className="flex flex-wrap items-center gap-3 mb-4">
        <Tabs value={status} onChange={(v) => setParam('status', v)} tabs={STATUS_TABS} />
        <select aria-label="Tipo de trabajo" className={`${selectCls} w-56`} value={type} onChange={(e) => setParam('type', e.target.value)}>
          <option value="">Todos los tipos</option>
          {Object.entries(JOB_TYPE).map(([id, t]) => (
            <option key={id} value={id}>
              {t.label}
            </option>
          ))}
        </select>
        <select aria-label="Cantidad" className={`${selectCls} w-32`} value={limit} onChange={(e) => setParam('limit', e.target.value === '50' ? '' : e.target.value)}>
          {[50, 100, 200].map((n) => (
            <option key={n} value={n}>
              Últimos {n}
            </option>
          ))}
        </select>
        {socket !== 'open' && (
          <span className="text-[11px] text-amber-300">Sin tiempo real: usa «Actualizar» para ver el progreso.</span>
        )}
      </div>

      {jobs.error && <ErrorBanner className="mb-4" error={jobs.error} onRetry={jobs.refetch} title="No se pudo leer la cola" />}

      <Card>
        {jobs.loading && !jobs.data && <LoadingBlock label="Cargando trabajos…" />}
        {jobs.data && visible.length === 0 && (
          <EmptyState icon="pending_actions" title="Sin trabajos con estos filtros">
            Los trabajos se crean desde la Biblioteca (indexar, detectar, etiquetar), el Editor (render) y Revisión (publicar).
          </EmptyState>
        )}
        <div className="divide-y divide-outline-variant/10">
          {visible.map((job) => (
            <JobRow key={job.id} job={job} expanded={expanded.has(job.id)} onToggle={() => toggle(job.id)} />
          ))}
        </div>
      </Card>
    </>
  );
}
