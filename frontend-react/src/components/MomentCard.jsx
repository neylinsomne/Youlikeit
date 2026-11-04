import { useState } from 'react';
import { api } from '../api/client';
import { useToast } from '../hooks/useToast';
import { fmtPct, fmtSeconds, msToClock } from '../lib/format';
import { DIMENSION_LABEL, DIMENSION_TONE, MOMENT_STATUS, WHY_LABELS, humanize } from '../lib/labels';
import SpecPicker from './SpecPicker';
import { Button, Icon, ProgressBar, StatusPill } from './ui';

const SOURCE_ICON = (source = '') =>
  source === 'manual' ? 'person' : source.startsWith('llm') ? 'auto_awesome' : 'bolt';

function LazyPreview({ src, startMs, endMs }) {
  const [state, setState] = useState('idle'); // idle | playing | error
  return (
    <div className="aspect-video bg-surface-dim relative">
      {state === 'playing' && (
        <video
          src={src}
          controls
          autoPlay
          playsInline
          preload="metadata"
          className="w-full h-full object-contain bg-black"
          onError={() => setState('error')}
        />
      )}
      {state === 'idle' && (
        <button
          type="button"
          onClick={() => setState('playing')}
          disabled={!src}
          className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-on-surface-variant hover:text-primary transition-colors cursor-pointer disabled:cursor-not-allowed"
        >
          <Icon name="play_circle" className="text-4xl" />
          <span className="text-[10px] uppercase tracking-widest font-bold">Ver vista previa</span>
        </button>
      )}
      {state === 'error' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-error text-xs p-4 text-center">
          <Icon name="videocam_off" className="text-3xl" />
          No se pudo cargar la vista previa.
          <button type="button" className="text-primary underline cursor-pointer" onClick={() => setState('playing')}>
            Reintentar
          </button>
        </div>
      )}
      {state !== 'playing' && (
        <>
          <span className="absolute top-2 left-2 bg-surface/80 backdrop-blur text-[10px] font-mono px-1.5 py-0.5 rounded">
            {msToClock(startMs)} – {msToClock(endMs)}
          </span>
          <span className="absolute top-2 right-2 bg-surface/80 backdrop-blur text-[10px] font-mono px-1.5 py-0.5 rounded">
            {fmtSeconds(endMs - startMs)}
          </span>
        </>
      )}
    </div>
  );
}

function WhyBars({ why }) {
  const entries = Object.entries(why || {})
    .filter(([, v]) => Number(v) > 0)
    .sort((a, b) => b[1] - a[1]);
  if (!entries.length) return null;
  const max = entries[0][1] || 1;
  return (
    <div>
      <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1.5">Por qué</p>
      <div className="space-y-1">
        {entries.slice(0, 5).map(([key, v]) => (
          <div key={key} className="flex items-center gap-2" title={`${key}: +${v}`}>
            <span className="text-[10px] text-on-surface-variant w-28 truncate">{WHY_LABELS[key] ?? humanize(key)}</span>
            <div className="flex-1 h-1.5 bg-surface-highest rounded-full overflow-hidden">
              <div className="h-full bg-primary/70 rounded-full" style={{ width: `${(v / max) * 100}%` }} />
            </div>
            <span className="text-[10px] font-mono text-on-surface-variant w-10 text-right">+{Number(v).toFixed(2)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Tarjeta de momento: vista previa diferida, etiquetas, "por qué", anclas y acciones.
 * `vocab` = useVocab() del padre. `onUpdated(moment)` recibe la respuesta del PATCH.
 */
export default function MomentCard({ moment, vocab, onUpdated, onAddToLesson }) {
  const toast = useToast();
  const [busy, setBusy] = useState(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ dimension: 'emotion', value: '' });

  const rejected = moment.status === 'rejected';
  const labels = moment.labels || [];
  const alreadyHas = labels.some((l) => l.dimension === draft.dimension && l.value === draft.value);
  const draftValid = Boolean(draft.value) && vocab.has(draft.dimension, draft.value) && !alreadyHas;

  const patch = async (body, what, okMessage) => {
    setBusy(what);
    try {
      const updated = await api.patchMoment(moment.id, body);
      onUpdated?.(updated);
      if (okMessage) toast.success(okMessage);
      return true;
    } catch (err) {
      toast.error(err, 'No se pudo actualizar el momento');
      return false;
    } finally {
      setBusy(null);
    }
  };

  const addLabel = async (e) => {
    e.preventDefault();
    if (!draftValid) return;
    const ok = await patch(
      { add_labels: [{ dimension: draft.dimension, value: draft.value }] },
      'add',
      `Etiqueta agregada: ${vocab.labelOf(draft.dimension, draft.value)}`,
    );
    if (ok) {
      setAdding(false);
      setDraft((d) => ({ ...d, value: '' }));
    }
  };

  return (
    <article
      className={`bg-surface-container rounded-xl border overflow-hidden flex flex-col transition-colors ${
        rejected ? 'border-error/20' : 'border-outline-variant/10 hover:border-primary/30'
      }`}
    >
      <LazyPreview src={moment.preview_url} startMs={moment.start_ms} endMs={moment.end_ms} />

      <div className={`p-4 space-y-3 flex-1 flex flex-col ${rejected ? 'opacity-70' : ''}`}>
        <header className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h4 className="text-sm font-bold leading-tight">
              {moment.work_title ?? moment.title ?? 'Obra'}{' '}
              <span className="text-on-surface-variant font-normal">({moment.work_year ?? moment.year ?? 's. f.'})</span>
            </h4>
            <p className="text-[10px] text-on-surface-variant mt-0.5">
              Momento #{moment.id}
              {moment.position !== undefined && moment.position !== null && ` · al ${Math.round(moment.position * 100)} % de la obra`}
            </p>
          </div>
          <StatusPill map={MOMENT_STATUS} status={moment.status} />
        </header>

        {moment.text && (
          <blockquote className="text-xs italic text-on-surface border-l-2 border-primary/40 pl-2 line-clamp-3" title={moment.text}>
            “{moment.text}”
          </blockquote>
        )}
        {moment.summary_es && <p className="text-xs text-on-surface-variant">{moment.summary_es}</p>}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <div className="flex justify-between text-[10px] text-on-surface-variant mb-1">
              <span>Importancia</span>
              <span className="font-mono">{fmtPct(moment.importance)}</span>
            </div>
            <ProgressBar value={(moment.importance ?? 0) * 100} tone="primary" />
          </div>
          {moment.score !== undefined ? (
            <div className="text-[10px] text-on-surface-variant">
              <div className="flex justify-between">
                <span>Puntaje</span>
                <span className="font-mono text-on-surface">{Number(moment.score).toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span>Confianza</span>
                <span className="font-mono text-on-surface">{fmtPct(moment.confidence)}</span>
              </div>
            </div>
          ) : (
            <div>
              <div className="flex justify-between text-[10px] text-on-surface-variant mb-1">
                <span>Señal</span>
                <span className="font-mono">{fmtPct(moment.signal_score)}</span>
              </div>
              <ProgressBar value={(moment.signal_score ?? 0) * 100} tone="neutral" />
            </div>
          )}
        </div>

        <WhyBars why={moment.why} />

        {(moment.anchors?.quote || moment.anchors?.plot) && (
          <div className="space-y-1.5">
            {moment.anchors.quote && (
              <p className="text-[11px]">
                <span className="text-[9px] font-bold uppercase tracking-widest text-tertiary mr-1.5">Cita</span>
                <span className="italic text-on-surface-variant">{moment.anchors.quote}</span>
              </p>
            )}
            {moment.anchors.plot && (
              <p className="text-[11px]">
                <span className="text-[9px] font-bold uppercase tracking-widest text-primary mr-1.5">Trama</span>
                <span className="text-on-surface-variant">{moment.anchors.plot}</span>
              </p>
            )}
          </div>
        )}

        <div>
          <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1.5">Etiquetas</p>
          <div className="flex flex-wrap gap-1.5">
            {labels.length === 0 && <span className="text-[11px] text-on-surface-variant">Sin etiquetas todavía.</span>}
            {labels.map((l) => {
              const key = `${l.dimension}:${l.value}`;
              return (
                <span
                  key={key}
                  title={`${DIMENSION_LABEL[l.dimension] ?? l.dimension} · fuente: ${l.source ?? '—'} · confianza ${fmtPct(l.confidence)}`}
                  className={`inline-flex items-center gap-1 text-[10px] font-bold pl-1.5 pr-1 py-0.5 rounded-full ring-1 ${DIMENSION_TONE[l.dimension] ?? DIMENSION_TONE.trope}`}
                >
                  <Icon name={SOURCE_ICON(l.source)} className="text-[11px]" />
                  {vocab.labelOf(l.dimension, l.value)}
                  {l.confidence !== undefined && l.confidence !== null && l.source !== 'manual' && (
                    <span className="font-mono font-normal opacity-70">{Math.round(l.confidence * 100)}</span>
                  )}
                  <button
                    type="button"
                    aria-label={`Quitar etiqueta ${vocab.labelOf(l.dimension, l.value)}`}
                    disabled={busy !== null}
                    onClick={() =>
                      patch({ remove_labels: [{ dimension: l.dimension, value: l.value }] }, `rm:${key}`)
                    }
                    className="hover:text-error cursor-pointer disabled:opacity-40"
                  >
                    <Icon name={busy === `rm:${key}` ? 'progress_activity' : 'close'} className={`text-[11px] ${busy === `rm:${key}` ? 'animate-spin' : ''}`} />
                  </button>
                </span>
              );
            })}
          </div>

          {adding ? (
            <form onSubmit={addLabel} className="mt-2 space-y-2">
              <SpecPicker vocab={vocab} dimension={draft.dimension} value={draft.value} onChange={setDraft} idPrefix={`m${moment.id}`} />
              {alreadyHas && <p className="text-[10px] text-amber-300">Esa etiqueta ya está.</p>}
              <div className="flex justify-end gap-2">
                <Button size="xs" variant="ghost" onClick={() => setAdding(false)}>
                  Cancelar
                </Button>
                <Button size="xs" variant="accent" type="submit" icon="add" disabled={!draftValid} loading={busy === 'add'}>
                  Agregar
                </Button>
              </div>
            </form>
          ) : (
            <button
              type="button"
              onClick={() => setAdding(true)}
              className="mt-2 text-[10px] font-bold text-primary flex items-center gap-1 cursor-pointer hover:underline"
            >
              <Icon name="new_label" className="text-sm" />
              Etiquetar a mano
            </button>
          )}
        </div>

        <footer className="mt-auto pt-2 flex flex-wrap gap-2">
          {rejected ? (
            <Button
              size="sm"
              variant="ok"
              icon="restore"
              loading={busy === 'status'}
              disabled={busy !== null}
              onClick={() => patch({ status: 'candidate' }, 'status', 'Momento restaurado')}
            >
              Restaurar
            </Button>
          ) : (
            <Button
              size="sm"
              variant="danger"
              icon="block"
              loading={busy === 'status'}
              disabled={busy !== null}
              onClick={() => patch({ status: 'rejected' }, 'status', 'Momento rechazado')}
            >
              Rechazar
            </Button>
          )}
          {onAddToLesson && (
            <Button
              size="sm"
              variant="accent"
              icon="playlist_add"
              disabled={rejected}
              title={rejected ? 'Restaura el momento para usarlo' : undefined}
              onClick={() => onAddToLesson(moment)}
            >
              Agregar a lección
            </Button>
          )}
        </footer>
      </div>
    </article>
  );
}
