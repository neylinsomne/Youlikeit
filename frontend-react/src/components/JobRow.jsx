import { Link } from 'react-router-dom';
import { fmtDate, fmtElapsed } from '../lib/format';
import { jobPct } from '../lib/jobs';
import { JOB_STATUS, JOB_TYPE } from '../lib/labels';
import { Icon, ProgressBar, StatusPill } from './ui';

const ICON_TONE = {
  queued: 'bg-surface-highest text-on-surface-variant',
  running: 'bg-primary/20 text-primary',
  done: 'bg-tertiary/20 text-tertiary',
  error: 'bg-error/20 text-error',
};

function ParamsSummary({ job }) {
  const p = job.params || {};
  if (p.lesson_id !== undefined) {
    const to = job.type === 'render' ? `/editor?id=${p.lesson_id}` : `/revision?id=${p.lesson_id}`;
    return (
      <Link to={to} className="text-[10px] text-primary hover:underline">
        Lección #{p.lesson_id}
      </Link>
    );
  }
  if (Array.isArray(p.asset_ids)) {
    return <span className="text-[10px] text-on-surface-variant">Asset {p.asset_ids.map((a) => `#${a}`).join(', ')}</span>;
  }
  if (p.asset_id !== undefined) {
    return <span className="text-[10px] text-on-surface-variant">Asset #{p.asset_id}</span>;
  }
  return null;
}

function JsonBlock({ label, value }) {
  if (value === null || value === undefined) return null;
  return (
    <div>
      <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1">{label}</p>
      <pre className="text-[11px] font-mono bg-surface-dim rounded-lg p-3 overflow-x-auto whitespace-pre-wrap break-words max-h-64">
        {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

/** Una fila de trabajo con progreso en vivo. `onToggle` habilita el detalle desplegable. */
export default function JobRow({ job, expanded = false, onToggle }) {
  const type = JOB_TYPE[job.type] ?? { label: job.type, icon: 'work' };
  const pct = jobPct(job);
  const active = job.status === 'running' || job.status === 'queued';
  const elapsed = fmtElapsed(job.started_at, job.finished_at);
  const stage = job.progress?.stage;
  const detail = job.progress?.detail;

  return (
    <div className="p-4">
      <div className="flex items-start gap-3">
        <div className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center ${ICON_TONE[job.status] ?? ICON_TONE.queued}`}>
          <Icon name={type.icon} className="text-sm" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-bold">{type.label}</span>
            <span className="text-[10px] font-mono text-on-surface-variant">#{job.id}</span>
            <StatusPill map={JOB_STATUS} status={job.status} />
            <ParamsSummary job={job} />
          </div>
          {active && (
            <div className="mt-2 flex items-center gap-2">
              <ProgressBar value={pct ?? 0} indeterminate={pct === null} />
              <span className="text-[10px] font-mono text-on-surface-variant w-10 text-right">
                {pct === null ? '…' : `${Math.round(pct)}%`}
              </span>
            </div>
          )}
          {(stage || detail) && (
            <p className="text-[10px] text-on-surface-variant mt-1 truncate">
              {stage && <span className="font-mono text-primary/80">{stage}</span>}
              {stage && detail && ' · '}
              {detail}
            </p>
          )}
          {job.status === 'error' && job.error && !expanded && (
            <p className="text-[11px] text-error mt-1 line-clamp-2 break-words">{job.error}</p>
          )}
        </div>
        <div className="text-right text-[10px] text-on-surface-variant flex-shrink-0">
          <div>{fmtDate(job.created_at)}</div>
          {elapsed && <div className="font-mono">{elapsed}</div>}
        </div>
        {onToggle && (
          <button
            type="button"
            onClick={onToggle}
            aria-expanded={expanded}
            aria-label={expanded ? 'Ocultar detalle' : 'Ver detalle'}
            className="text-on-surface-variant hover:text-on-surface cursor-pointer"
          >
            <Icon name={expanded ? 'expand_less' : 'expand_more'} />
          </button>
        )}
      </div>
      {expanded && (
        <div className="mt-3 ml-11 space-y-3">
          <div className="grid grid-cols-3 gap-2 text-[10px] text-on-surface-variant">
            <span>Creado: {fmtDate(job.created_at)}</span>
            <span>Inicio: {fmtDate(job.started_at)}</span>
            <span>Fin: {fmtDate(job.finished_at)}</span>
          </div>
          {job.error && <JsonBlock label="Error" value={job.error} />}
          <JsonBlock label="Parámetros" value={job.params} />
          <JsonBlock label="Resultado" value={job.result} />
        </div>
      )}
    </div>
  );
}
