import { useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, versionedUrl } from '../api/client';
import ClockInput from '../components/ClockInput';
import SpecPicker from '../components/SpecPicker';
import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorBanner,
  Field,
  Icon,
  LoadingBlock,
  Notice,
  PageHeader,
  Pill,
  ProgressBar,
  StatusPill,
  Tabs,
} from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useDebouncedValue } from '../hooks/useDebounced';
import { useJobTracker } from '../hooks/useJobsSocket';
import { useToast } from '../hooks/useToast';
import { useVocab } from '../hooks/useVocab';
import { fmtDate, fmtSeconds, msToClock, splitSpec } from '../lib/format';
import { isTerminal, jobPct } from '../lib/jobs';
import { DIMENSION_LABEL, LESSON_STATUS, suggestedMood } from '../lib/labels';
import { EDIT_RESETS_STATUS, MAX_LESSON_MS, itemsDurationMs, toItemPatch } from '../lib/lesson';
import { inputCls, selectCls, textareaCls } from '../lib/styles';

const NO_ITEMS = [];
const MIN_ITEM_MS = 500;
const SOFT_LIMIT_MS = 58000;
const NUDGE_MS = 500;

// ───────────────────────────── Modelo del borrador ─────────────────────────────

function initDraft(lesson) {
  const script = lesson.script ?? null;
  const segments = new Map((script?.segments ?? []).map((s) => [s.idx, s]));
  const { hook = '', outro = '', segments: _segments, ...scriptExtra } = script ?? {};
  return {
    title: lesson.title ?? '',
    hasScript: Boolean(script),
    hook: hook ?? '',
    outro: outro ?? '',
    scriptExtra,
    items: (lesson.items ?? []).map((it, i) => {
      const seg = segments.get(it.idx ?? i);
      return {
        ...it,
        uid: `${it.moment_id}:${i}`,
        caption: it.caption ?? '',
        narration: seg?.narration ?? '',
        aiCaption: seg?.caption ?? '',
      };
    }),
  };
}

function patchBody(draft) {
  const body = { title: draft.title.trim(), items: draft.items.map(toItemPatch) };
  if (draft.hasScript) {
    body.script = {
      ...draft.scriptExtra,
      hook: draft.hook,
      outro: draft.outro,
      segments: draft.items.map((it, i) => ({
        idx: i,
        narration: it.narration ?? '',
        caption: it.aiCaption || it.caption || '',
      })),
    };
  }
  return body;
}

function itemError(it) {
  if (it.in_ms < 0) return 'La entrada no puede ser negativa.';
  if (it.out_ms <= it.in_ms) return 'La salida debe ir después de la entrada.';
  if (it.out_ms - it.in_ms < MIN_ITEM_MS) return 'El recorte dura menos de medio segundo.';
  return null;
}

// ───────────────────────────── Nueva lección ─────────────────────────────

function NewLessonForm({ vocab, initialSpec, onCreated, onCancel }) {
  const toast = useToast();
  const [dim0, val0] = splitSpec(initialSpec);
  const [form, setForm] = useState({
    dimension: dim0 || 'emotion',
    value: val0 || '',
    title: '',
    max_works: 5,
    max_duration_s: 58,
    lang: 'es',
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (patch) => setForm((f) => ({ ...f, ...patch }));

  const submit = async (e) => {
    e.preventDefault();
    if (!form.value) return;
    setBusy(true);
    setError(null);
    try {
      const body = {
        spec: `${form.dimension}:${form.value}`,
        max_works: Number(form.max_works) || 5,
        max_duration_s: Number(form.max_duration_s) || 58,
        lang: form.lang,
      };
      if (form.title.trim()) body.title = form.title.trim();
      const lesson = await api.createLesson(body);
      toast.success(`Lección creada: ${lesson.title}`, `${lesson.items?.length ?? 0} momentos de distintas obras.`);
      onCreated(lesson);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="mb-6">
      <CardHeader
        title="Nueva lección por tema"
        icon="auto_awesome_motion"
        subtitle="El planificador elige momentos del mismo tema en obras distintas y arma un corte de hasta 60 s."
        actions={
          onCancel && (
            <Button size="sm" variant="ghost" icon="close" onClick={onCancel}>
              Cerrar
            </Button>
          )
        }
      />
      <form onSubmit={submit} className="p-4 grid grid-cols-12 gap-3 items-end">
        <Field label="Tema" className="col-span-12 lg:col-span-5">
          <SpecPicker vocab={vocab} dimension={form.dimension} value={form.value} onChange={set} idPrefix="nueva" required />
        </Field>
        <Field label="Título (opcional)" className="col-span-12 lg:col-span-3">
          {(id) => <input id={id} className={inputCls} value={form.title} placeholder="El miedo a través de las décadas" onChange={(e) => set({ title: e.target.value })} />}
        </Field>
        <Field label="Obras máx." className="col-span-4 lg:col-span-1">
          {(id) => <input id={id} type="number" min={2} max={8} className={`${inputCls} font-mono`} value={form.max_works} onChange={(e) => set({ max_works: e.target.value })} />}
        </Field>
        <Field label="Duración máx. (s)" className="col-span-4 lg:col-span-1">
          {(id) => <input id={id} type="number" min={15} max={60} className={`${inputCls} font-mono`} value={form.max_duration_s} onChange={(e) => set({ max_duration_s: e.target.value })} />}
        </Field>
        <Field label="Idioma" className="col-span-4 lg:col-span-1">
          {(id) => (
            <select id={id} className={selectCls} value={form.lang} onChange={(e) => set({ lang: e.target.value })}>
              <option value="es">Español</option>
              <option value="en">Inglés</option>
            </select>
          )}
        </Field>
        <div className="col-span-12 lg:col-span-1">
          <Button type="submit" variant="primary" icon="auto_awesome" className="w-full" loading={busy} disabled={!form.value}>
            Armar
          </Button>
        </div>
      </form>
      {error && (
        <div className="px-4 pb-4">
          <ErrorBanner error={error} title={error.status === 409 ? 'No hay suficientes obras con ese tema' : 'No se pudo crear la lección'} />
          {error.status === 409 && (
            <p className="text-[11px] text-on-surface-variant mt-2">
              Revisa cuántas obras tienen ese tema en{' '}
              <Link className="text-primary underline" to={`/momentos?tab=buscar&spec=${encodeURIComponent(`${form.dimension}:${form.value}`)}`}>
                Momentos → Buscar entre obras
              </Link>{' '}
              e indexa/etiqueta más películas en la Biblioteca.
            </p>
          )}
        </div>
      )}
    </Card>
  );
}

// ───────────────────────────── Biblioteca de momentos ─────────────────────────────

function MomentLibrary({ spec, vocab, usedIds, onAdd, disabled }) {
  const [dimension, value] = splitSpec(spec);
  const [scope, setScope] = useState(dimension ? 'tema' : 'todos');
  const [q, setQ] = useState('');
  const dq = useDebouncedValue(q.trim(), 400);
  const params = scope === 'tema' && dimension ? { dimension, value, q: dq, per_page: 30 } : { q: dq, per_page: 30 };
  const moments = useApi((signal) => api.moments(params, { signal }), [params]);
  const items = (moments.data?.items ?? NO_ITEMS).filter((m) => m.status !== 'rejected');

  return (
    <Card>
      <CardHeader
        title="Momentos para agregar"
        icon="movie_filter"
        subtitle="Arrastra a la línea de tiempo o usa +."
        actions={
          <Tabs
            value={scope}
            onChange={setScope}
            tabs={[
              ...(dimension ? [{ id: 'tema', label: vocab.labelOf(dimension, value) }] : []),
              { id: 'todos', label: 'Todos' },
            ]}
          />
        }
      />
      <div className="p-4">
        <input className={`${inputCls} mb-3`} placeholder="Filtrar por texto…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filtrar momentos por texto" />
        {moments.error && <ErrorBanner error={moments.error} onRetry={moments.refetch} />}
        {moments.loading && !moments.data && <LoadingBlock />}
        {moments.data && items.length === 0 && <p className="text-xs text-on-surface-variant text-center py-6">Sin momentos para este filtro.</p>}
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2 max-h-80 overflow-y-auto pr-1">
          {items.map((m) => {
            const used = usedIds.has(m.id);
            return (
              <div
                key={m.id}
                draggable={!disabled}
                onDragStart={(e) => {
                  e.dataTransfer.setData(
                    'application/x-moment',
                    JSON.stringify({
                      id: m.id,
                      start_ms: m.start_ms,
                      end_ms: m.end_ms,
                      work_title: m.work_title,
                      work_year: m.work_year,
                      text: m.text,
                      preview_url: m.preview_url,
                    }),
                  );
                  e.dataTransfer.effectAllowed = 'copy';
                }}
                className={`group rounded-lg border p-2.5 bg-surface-low ${disabled ? 'opacity-50' : 'cursor-grab active:cursor-grabbing'} ${
                  used ? 'border-tertiary/30' : 'border-outline-variant/10 hover:border-primary/40'
                }`}
              >
                <div className="flex items-start justify-between gap-1">
                  <div className="min-w-0">
                    <div className="text-[11px] font-bold truncate">{m.work_title}</div>
                    <div className="text-[10px] text-on-surface-variant font-mono">
                      {m.work_year ?? 's. f.'} · {fmtSeconds(m.end_ms - m.start_ms)}
                    </div>
                  </div>
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onAdd(m)}
                    aria-label="Agregar al final"
                    className="text-primary hover:text-primary-glow cursor-pointer disabled:opacity-40"
                  >
                    <Icon name="add_circle" className="text-lg" />
                  </button>
                </div>
                {m.text && <p className="text-[10px] italic text-on-surface-variant mt-1 line-clamp-2">“{m.text}”</p>}
                {used && <p className="text-[9px] font-bold uppercase tracking-widest text-tertiary mt-1">Ya en la lección</p>}
              </div>
            );
          })}
        </div>
      </div>
    </Card>
  );
}

// ───────────────────────────── Línea de tiempo ─────────────────────────────

function readDrop(e) {
  const from = e.dataTransfer.getData('text/x-lesson-item');
  if (from !== '') return { kind: 'item', from: Number(from) };
  const raw = e.dataTransfer.getData('application/x-moment');
  if (!raw) return null;
  try {
    return { kind: 'moment', moment: JSON.parse(raw) };
  } catch {
    return null; // arrastre de otra app: se ignora
  }
}

function Timeline({ items, selected, onSelect, onMove, onInsert, disabled }) {
  const [over, setOver] = useState(null);
  const drop = (e, at) => {
    e.preventDefault();
    setOver(null);
    if (disabled) return;
    const d = readDrop(e);
    if (d?.kind === 'item') onMove(d.from, at);
    else if (d?.kind === 'moment') onInsert(d.moment, at);
  };

  return (
    <div className="flex items-stretch gap-2 overflow-x-auto pb-2">
      {items.map((it, i) => {
        const dur = it.out_ms - it.in_ms;
        const bad = itemError(it);
        const active = i === selected;
        return (
          <div
            key={it.uid}
            role="button"
            tabIndex={0}
            draggable={!disabled}
            onDragStart={(e) => {
              e.dataTransfer.setData('text/x-lesson-item', String(i));
              e.dataTransfer.effectAllowed = 'move';
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(i);
            }}
            onDragLeave={() => setOver(null)}
            onDrop={(e) => drop(e, i)}
            onClick={() => onSelect(i)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') onSelect(i);
            }}
            style={{ width: `${Math.max(150, Math.min(420, (dur / MAX_LESSON_MS) * 1100))}px` }}
            className={`flex-shrink-0 h-24 rounded-lg p-2 flex flex-col justify-between relative transition-all cursor-pointer border-2 ${
              bad
                ? 'border-error/60 bg-error-container/10'
                : active
                  ? 'border-primary-glow bg-primary-glow/10'
                  : 'border-primary-glow/20 bg-surface-high hover:border-primary-glow/50'
            } ${over === i ? 'ring-2 ring-tertiary ring-offset-2 ring-offset-surface-container' : ''}`}
          >
            <div className="flex items-center justify-between gap-1">
              <span className="flex items-center gap-1 min-w-0">
                <Icon name="drag_indicator" className="text-sm text-on-surface-variant" />
                <span className="text-[10px] font-bold truncate">
                  {i + 1}. {it.work_title ?? `Momento ${it.moment_id}`}
                </span>
              </span>
              <span className="text-[9px] font-mono text-on-surface-variant flex-shrink-0">{fmtSeconds(dur)}</span>
            </div>
            <div className="text-[9px] font-mono text-on-surface-variant">
              {it.work_year ?? ''} · {msToClock(it.in_ms)}
            </div>
            <div className={`text-[10px] truncate ${it.caption ? 'text-tertiary' : 'text-on-surface-variant/60 italic'}`}>
              {it.caption || 'sin texto en pantalla'}
            </div>
          </div>
        );
      })}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setOver('end');
        }}
        onDragLeave={() => setOver(null)}
        onDrop={(e) => drop(e, items.length)}
        className={`flex-shrink-0 w-36 h-24 rounded-lg border-2 border-dashed flex flex-col items-center justify-center gap-1 text-[10px] text-on-surface-variant transition-colors ${
          over === 'end' ? 'border-primary-glow bg-primary-glow/10' : 'border-outline-variant/30'
        }`}
      >
        <Icon name="add" />
        Suelta aquí
      </div>
    </div>
  );
}

function DurationMeter({ ms }) {
  const pct = (ms / MAX_LESSON_MS) * 100;
  const tone = ms > MAX_LESSON_MS ? 'error' : ms > SOFT_LIMIT_MS ? 'warn' : 'ok';
  return (
    <div>
      <div className="flex items-baseline justify-between text-xs mb-1">
        <span className="text-on-surface-variant">Duración de los recortes</span>
        <span className={`font-mono font-bold ${tone === 'error' ? 'text-error' : tone === 'warn' ? 'text-amber-300' : 'text-tertiary'}`}>
          {fmtSeconds(ms)} / 60 s
        </span>
      </div>
      <ProgressBar value={Math.min(100, pct)} tone={tone} />
      {ms > MAX_LESSON_MS && <p className="text-[10px] text-error mt-1">Pasa de 60 s: recorta o quita un momento.</p>}
    </div>
  );
}

// ───────────────────────────── Vista previa ─────────────────────────────

function ItemPreview({ item, moment }) {
  const videoRef = useRef(null);
  const stopAt = useRef(null);
  const base = moment?.start_ms ?? null;
  const inS = base !== null ? Math.max(0, (item.in_ms - base) / 1000) : 0;
  const outS = base !== null ? Math.max(0, (item.out_ms - base) / 1000) : null;
  const outside = base !== null && moment?.end_ms !== undefined && (item.in_ms < base || item.out_ms > moment.end_ms);

  const playCut = () => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = inS;
    stopAt.current = outS;
    v.play().catch((err) => console.warn('[estudio] el navegador no pudo reproducir', err));
  };

  return (
    <div className="space-y-2">
      <div className="aspect-video bg-black rounded-lg overflow-hidden">
        <video
          key={item.preview_url}
          ref={videoRef}
          src={item.preview_url}
          controls
          playsInline
          preload="metadata"
          className="w-full h-full object-contain"
          onLoadedMetadata={(e) => {
            e.currentTarget.currentTime = inS;
          }}
          onTimeUpdate={(e) => {
            if (stopAt.current !== null && e.currentTarget.currentTime >= stopAt.current) {
              e.currentTarget.pause();
              stopAt.current = null;
            }
          }}
          onSeeking={(e) => {
            if (Math.abs(e.currentTarget.currentTime - inS) > 0.3) stopAt.current = null;
          }}
        />
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[10px] text-on-surface-variant">
          Vista previa del momento{base === null ? ' (cargando límites…)' : ''}.
        </span>
        <Button size="xs" variant="accent" icon="play_arrow" onClick={playCut}>
          Reproducir recorte
        </Button>
      </div>
      {outside && (
        <p className="text-[10px] text-amber-300">El recorte sale del momento original: la vista previa solo cubre {msToClock(base)} – {msToClock(moment.end_ms)}.</p>
      )}
    </div>
  );
}

// ───────────────────────────── Editor de un item ─────────────────────────────

function ItemEditor({ item, index, count, moment, hasScript, disabled, onChange, onMove, onRemove }) {
  const err = itemError(item);
  const nudge = (field, delta) => onChange({ [field]: Math.max(0, item[field] + delta) });

  const timeField = (field, label) => (
    <div>
      <span className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant block mb-1">{label}</span>
      <div className="flex items-center gap-1">
        <Button size="xs" variant="ghost" icon="remove" aria-label={`${label} −0.5 s`} disabled={disabled} onClick={() => nudge(field, -NUDGE_MS)} />
        <ClockInput key={item[field]} valueMs={item[field]} disabled={disabled} invalid={Boolean(err)} aria-label={label} onCommit={(ms) => onChange({ [field]: ms })} />
        <Button size="xs" variant="ghost" icon="add" aria-label={`${label} +0.5 s`} disabled={disabled} onClick={() => nudge(field, NUDGE_MS)} />
      </div>
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">
            Segmento {index + 1} de {count}
          </p>
          <h4 className="text-sm font-bold">
            {item.work_title} <span className="font-normal text-on-surface-variant">({item.work_year ?? 's. f.'})</span>
          </h4>
          {moment && (
            <p className="text-[10px] text-on-surface-variant font-mono">
              Momento #{item.moment_id}: {msToClock(moment.start_ms)} – {msToClock(moment.end_ms)}
            </p>
          )}
        </div>
        <div className="flex items-center gap-1">
          <Button size="xs" variant="ghost" icon="arrow_back" aria-label="Mover antes" disabled={disabled || index === 0} onClick={() => onMove(index, index - 1)} />
          <Button size="xs" variant="ghost" icon="arrow_forward" aria-label="Mover después" disabled={disabled || index === count - 1} onClick={() => onMove(index, index + 2)} />
          <Button size="xs" variant="danger" icon="delete" disabled={disabled} onClick={() => onRemove(index)}>
            Quitar
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-4">
        {timeField('in_ms', 'Entrada')}
        {timeField('out_ms', 'Salida')}
        <div className="text-xs">
          <span className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant block mb-1">Dura</span>
          <span className="font-mono font-bold">{fmtSeconds(item.out_ms - item.in_ms)}</span>
        </div>
      </div>
      {err && <p className="text-[11px] text-error">{err}</p>}

      {item.text && (
        <blockquote className="text-xs italic text-on-surface-variant border-l-2 border-primary/40 pl-2">“{item.text}”</blockquote>
      )}

      <Field label="Texto en pantalla" hint={`${item.caption.length}/90 · una idea corta, se lee en 2-3 s`}>
        {(id) => (
          <textarea
            id={id}
            rows={2}
            maxLength={90}
            disabled={disabled}
            className={textareaCls}
            value={item.caption}
            placeholder="El miedo es una alarma, no una orden."
            onChange={(e) => onChange({ caption: e.target.value })}
          />
        )}
      </Field>
      {item.aiCaption && item.aiCaption !== item.caption && (
        <div className="flex items-start gap-2 text-[11px] bg-surface-low rounded-lg px-3 py-2">
          <Icon name="auto_awesome" className="text-sm text-primary" />
          <span className="flex-1 text-on-surface-variant">
            Sugerencia del guion: <span className="text-on-surface">{item.aiCaption}</span>
          </span>
          <button type="button" disabled={disabled} className="text-primary font-bold cursor-pointer hover:underline" onClick={() => onChange({ caption: item.aiCaption.slice(0, 90) })}>
            Usar
          </button>
        </div>
      )}

      {hasScript && (
        <Field label="Narración (voz en off)" hint="Opcional. Déjala vacía para que el segmento hable por sí mismo.">
          {(id) => (
            <textarea id={id} rows={3} disabled={disabled} className={textareaCls} value={item.narration} onChange={(e) => onChange({ narration: e.target.value })} />
          )}
        </Field>
      )}
    </div>
  );
}

// ───────────────────────────── Espacio de trabajo ─────────────────────────────

function LessonWorkspace({ lesson, vocab, selected, setSelected, renderJob, aiNotice, onAiStatus, onLessonChange, onRenderQueued, refetchLesson }) {
  const toast = useToast();
  const [draft, setDraft] = useState(() => initDraft(lesson));
  const initialBody = useMemo(() => JSON.stringify(patchBody(initDraft(lesson))), [lesson]);
  const [busy, setBusy] = useState(null); // save | script | render
  const nextUid = useRef(0);

  const items = draft.items;
  const dirty = JSON.stringify(patchBody(draft)) !== initialBody;
  const invalid = items.some((it) => itemError(it)) || !draft.title.trim() || items.length === 0;
  const totalMs = itemsDurationMs(items);
  const usedIds = useMemo(() => new Set(items.map((it) => it.moment_id)), [items]);
  const works = new Set(items.map((it) => it.work_title)).size;
  const rendering = lesson.status === 'rendering' || (renderJob && !isTerminal(renderJob.status));
  const locked = rendering || lesson.status === 'published';
  const sel = Math.min(selected, Math.max(0, items.length - 1));
  const current = items[sel] ?? null;
  const [dimension, value] = splitSpec(lesson.spec);

  const moment = useApi((signal) => api.moment(current.moment_id, { signal }), [current?.moment_id], { enabled: Boolean(current) });
  const [view, setView] = useState(lesson.video_url ? 'video' : 'item');

  const setItems = (fn) => setDraft((d) => ({ ...d, items: fn(d.items) }));
  const updateItem = (i, patch) => setItems((list) => list.map((it, j) => (j === i ? { ...it, ...patch } : it)));
  const move = (from, to) => {
    const target = from < to ? to - 1 : to;
    if (target === from) return;
    setItems((list) => {
      const next = [...list];
      const [it] = next.splice(from, 1);
      next.splice(target, 0, it);
      return next;
    });
    setSelected(target);
  };
  const remove = (i) => {
    setItems((list) => list.filter((_, j) => j !== i));
    setSelected(Math.max(0, i - 1));
  };
  const insert = (m, at = items.length) => {
    nextUid.current += 1;
    const uid = `nuevo-${m.id}-${nextUid.current}`;
    const item = {
      uid,
      idx: at,
      moment_id: m.id,
      work_title: m.work_title,
      work_year: m.work_year,
      in_ms: m.start_ms,
      out_ms: m.end_ms,
      caption: '',
      text: m.text,
      preview_url: m.preview_url,
      narration: '',
      aiCaption: '',
    };
    setItems((list) => [...list.slice(0, at), item, ...list.slice(at)]);
    setSelected(at);
    setView('item');
  };

  const save = async ({ quiet = false } = {}) => {
    setBusy('save');
    try {
      const updated = await api.patchLesson(lesson.id, patchBody(draft));
      if (!quiet) toast.success('Lección guardada');
      return updated;
    } catch (err) {
      toast.error(err, 'No se pudo guardar');
      return null;
    } finally {
      setBusy(null);
    }
  };

  const onSave = async () => {
    const updated = await save();
    if (updated) onLessonChange(updated);
  };

  const onScript = async () => {
    if (dirty && !(await save({ quiet: true }))) return;
    setBusy('script');
    try {
      const updated = await api.generateScript(lesson.id);
      toast.success('Guion generado con IA', 'Revísalo: títulos y años salen de la base de datos.');
      onAiStatus(null);
      onLessonChange(updated);
    } catch (err) {
      if (err?.status === 502) {
        toast.warn('IA no disponible: se dejó la plantilla', err.detail);
        onAiStatus(err.detail || 'El proveedor de IA no respondió.');
        refetchLesson();
      } else {
        toast.error(err, 'No se pudo generar el guion');
      }
    } finally {
      setBusy(null);
    }
  };

  const onRender = async () => {
    if (dirty && !(await save({ quiet: true }))) return;
    setBusy('render');
    try {
      const job = await api.renderLesson(lesson.id);
      onRenderQueued(job);
      toast.info(`Render en cola (trabajo #${job.id})`, 'El progreso aparece aquí en vivo.');
    } catch (err) {
      toast.error(err, 'No se pudo iniciar el render');
    } finally {
      setBusy(null);
      refetchLesson();
    }
  };

  const pct = renderJob ? jobPct(renderJob) : null;

  return (
    <div className="grid grid-cols-12 gap-6">
      {/* Columna principal */}
      <div className="col-span-12 xl:col-span-8 space-y-6">
        <Card>
          <CardHeader
            title="Vista previa"
            icon="smart_display"
            actions={
              <Tabs
                value={view}
                onChange={setView}
                tabs={[
                  { id: 'video', label: 'Lección renderizada', icon: 'movie' },
                  { id: 'item', label: 'Recorte seleccionado', icon: 'content_cut' },
                ]}
              />
            }
          />
          <div className="p-4">
            {view === 'video' ? (
              lesson.video_url ? (
                <div className="flex flex-col items-center gap-2">
                  <video
                    key={lesson.updated_at}
                    src={versionedUrl(lesson.video_url, lesson.updated_at)}
                    controls
                    playsInline
                    preload="metadata"
                    className="aspect-[9/16] max-h-[560px] bg-black rounded-lg"
                  />
                  <p className="text-[10px] text-on-surface-variant">
                    {lesson.duration_s ? `${Number(lesson.duration_s).toFixed(1)} s · ` : ''}actualizado {fmtDate(lesson.updated_at)}
                    {dirty && ' · hay cambios sin renderizar'}
                  </p>
                </div>
              ) : (
                <EmptyState icon="movie" title="Todavía no hay render">
                  Ajusta la línea de tiempo y pulsa «Renderizar».
                </EmptyState>
              )
            ) : current ? (
              <ItemPreview item={current} moment={moment.data?.id === current.moment_id ? moment.data : null} />
            ) : (
              <EmptyState icon="content_cut" title="Sin segmentos">
                Agrega momentos desde la lista de abajo.
              </EmptyState>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Línea de tiempo"
            icon="view_timeline"
            subtitle="Arrastra para reordenar. El ancho es proporcional a la duración."
            actions={
              <span className="text-[10px] text-on-surface-variant font-mono">
                {items.length} segmentos · {works} obras
              </span>
            }
          />
          <div className="p-4 space-y-3">
            <Timeline
              items={items}
              selected={sel}
              disabled={locked}
              onSelect={(i) => {
                setSelected(i);
                setView('item');
              }}
              onMove={move}
              onInsert={insert}
            />
            <DurationMeter ms={totalMs} />
            {works < 2 && items.length > 0 && <Notice>Una lección de empatía compara obras: suma momentos de al menos 2 películas distintas.</Notice>}
          </div>
        </Card>

        {current && (
          <Card className="p-4">
            <ItemEditor
              item={current}
              index={sel}
              count={items.length}
              moment={moment.data?.id === current.moment_id ? moment.data : null}
              hasScript={draft.hasScript}
              disabled={locked}
              onChange={(patch) => updateItem(sel, patch)}
              onMove={move}
              onRemove={remove}
            />
          </Card>
        )}

        <MomentLibrary key={lesson.spec} spec={lesson.spec} vocab={vocab} usedIds={usedIds} disabled={locked} onAdd={(m) => insert(m)} />
      </div>

      {/* Columna lateral */}
      <div className="col-span-12 xl:col-span-4 space-y-6">
        <Card>
          <CardHeader title="Lección" icon="movie_edit" actions={<StatusPill map={LESSON_STATUS} status={lesson.status} />} />
          <div className="p-4 space-y-4">
            <Field label="Título">
              {(id) => (
                <input id={id} className={inputCls} disabled={locked} value={draft.title} onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))} />
              )}
            </Field>
            <div className="flex flex-wrap gap-2 text-[10px]">
              {dimension && (
                <Pill tone="info" icon="label">
                  {DIMENSION_LABEL[dimension] ?? dimension}: {vocab.labelOf(dimension, value)}
                </Pill>
              )}
              {lesson.format && <Pill>{lesson.format}</Pill>}
              {lesson.lang && <Pill>{lesson.lang === 'es' ? 'Español' : lesson.lang}</Pill>}
              {lesson.issues > 0 && (
                <Pill tone="warn" icon="flag">
                  {lesson.issues} {lesson.issues === 1 ? 'issue' : 'issues'}
                </Pill>
              )}
            </div>
            <DurationMeter ms={totalMs} />
            {lesson.status === 'rejected' && lesson.reject_reason && (
              <Notice tone="error" icon="block">
                Rechazada: {lesson.reject_reason}
              </Notice>
            )}
            {dirty && EDIT_RESETS_STATUS.has(lesson.status) && (
              <Notice>Al guardar, la lección vuelve a borrador y hay que renderizarla de nuevo.</Notice>
            )}
            {lesson.status === 'published' && <Notice tone="info">Lección publicada: ya no se edita. Crea otra para variar el corte.</Notice>}

            {renderJob && (
              <div className="rounded-lg bg-surface-low p-3 space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-bold flex items-center gap-1.5">
                    <Icon name="movie" className="text-sm text-primary" />
                    Render #{renderJob.id}
                  </span>
                  <span className="font-mono text-on-surface-variant">{pct === null ? '…' : `${Math.round(pct)}%`}</span>
                </div>
                <ProgressBar value={pct ?? 0} indeterminate={pct === null && !isTerminal(renderJob.status)} tone={renderJob.status === 'error' ? 'error' : renderJob.status === 'done' ? 'ok' : 'info'} />
                <p className="text-[10px] text-on-surface-variant">
                  {renderJob.progress?.stage}
                  {renderJob.progress?.detail ? ` · ${renderJob.progress.detail}` : ''}
                </p>
                {renderJob.status === 'error' && <p className="text-[11px] text-error break-words">{renderJob.error || renderJob.progress?.detail || 'El render falló.'}</p>}
              </div>
            )}

            <div className="grid grid-cols-2 gap-2">
              <Button variant="subtle" icon="save" disabled={!dirty || invalid || locked || busy !== null} loading={busy === 'save'} onClick={onSave}>
                Guardar
              </Button>
              <Button variant="ghost" icon="undo" disabled={!dirty || busy !== null} onClick={() => setDraft(initDraft(lesson))}>
                Descartar
              </Button>
            </div>
            <Button
              variant="primary"
              size="lg"
              icon="movie"
              className="w-full"
              disabled={invalid || locked || busy !== null || totalMs > MAX_LESSON_MS}
              loading={busy === 'render'}
              onClick={onRender}
            >
              {dirty ? 'Guardar y renderizar' : lesson.video_url ? 'Renderizar de nuevo' : 'Renderizar'}
            </Button>
            {lesson.status === 'rendered' && (
              <Link
                to={`/revision?id=${lesson.id}`}
                className="font-headline w-full text-xs font-bold uppercase tracking-widest py-2.5 rounded-lg bg-tertiary/15 text-tertiary border border-tertiary/30 hover:bg-tertiary/25 flex items-center justify-center gap-1.5"
              >
                <Icon name="rate_review" className="text-sm" />
                Ir a revisión
              </Link>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Guion"
            icon="record_voice_over"
            actions={
              <Button size="sm" variant="accent" icon="auto_awesome" disabled={locked || busy !== null || invalid} loading={busy === 'script'} onClick={onScript}>
                {draft.hasScript ? 'Regenerar con IA' : 'Generar con IA'}
              </Button>
            }
          />
          <div className="p-4 space-y-4">
            {aiNotice && (
              <Notice tone="warn" icon="cloud_off">
                <b>IA no disponible: se dejó la plantilla.</b>
                {aiNotice.detail && <span className="block opacity-80 mt-0.5">{aiNotice.detail}</span>}
              </Notice>
            )}
            {draft.hasScript ? (
              <>
                <Field label="Gancho (primeros 2 s)">
                  {(id) => <textarea id={id} rows={2} disabled={locked} className={textareaCls} value={draft.hook} onChange={(e) => setDraft((d) => ({ ...d, hook: e.target.value }))} />}
                </Field>
                <Field label="Cierre">
                  {(id) => <textarea id={id} rows={2} disabled={locked} className={textareaCls} value={draft.outro} onChange={(e) => setDraft((d) => ({ ...d, outro: e.target.value }))} />}
                </Field>
                <div>
                  <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1.5">Narración por segmento</p>
                  <ol className="space-y-1">
                    {items.map((it, i) => (
                      <li key={it.uid}>
                        <button
                          type="button"
                          onClick={() => {
                            setSelected(i);
                            setView('item');
                          }}
                          className={`w-full text-left text-[11px] rounded-md px-2 py-1 cursor-pointer ${i === sel ? 'bg-primary-glow/10 text-on-surface' : 'text-on-surface-variant hover:bg-surface-high'}`}
                        >
                          <span className="font-mono mr-1">{i + 1}.</span>
                          {it.narration || <span className="italic opacity-60">sin narración</span>}
                        </button>
                      </li>
                    ))}
                  </ol>
                  <p className="text-[10px] text-on-surface-variant mt-1">Edita cada narración desde el segmento seleccionado.</p>
                </div>
              </>
            ) : (
              <EmptyState icon="record_voice_over" title="Sin guion" className="py-4">
                Genera uno con IA o escríbelo a mano.
                <div className="mt-3">
                  <Button size="sm" variant="subtle" icon="edit_note" disabled={locked} onClick={() => setDraft((d) => ({ ...d, hasScript: true }))}>
                    Escribir a mano
                  </Button>
                </div>
              </EmptyState>
            )}
          </div>
        </Card>

        <Card className="p-4">
          <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1 flex items-center gap-1">
            <Icon name="music_note" className="text-sm text-tertiary" />
            Mood sugerido
          </p>
          <p className="text-sm font-bold text-tertiary">{suggestedMood(lesson.spec, lesson.script)}</p>
          <p className="text-[10px] text-on-surface-variant mt-1">
            La música no se mezcla aquí: se elige en TikTok/YouTube al publicar.
          </p>
        </Card>
      </div>
    </div>
  );
}

// ───────────────────────────── Página ─────────────────────────────

export default function Editor() {
  const toast = useToast();
  const [sp, setSp] = useSearchParams();
  const lessonId = Number(sp.get('id')) || null;
  const showNew = sp.get('nueva') === '1' || !lessonId;
  const vocab = useVocab();
  const [selected, setSelected] = useState(0);
  const [aiNotice, setAiNotice] = useState(null);

  const lessons = useApi((signal) => api.lessons({}, { signal }), []);
  const lesson = useApi((signal) => api.lesson(lessonId, { signal }), [lessonId], { enabled: Boolean(lessonId) });
  const current = lesson.data?.id === lessonId ? lesson.data : null;

  // Si la lección ya estaba renderizando al abrirla, buscamos su job para seguirlo.
  const pending = useApi((signal) => api.jobs({ limit: 50 }, { signal }), [lessonId], { enabled: current?.status === 'rendering' });
  const fallbackJob =
    current?.status === 'rendering'
      ? ((pending.data?.items ?? NO_ITEMS).find((j) => j.type === 'render' && j.params?.lesson_id === lessonId && !isTerminal(j.status)) ?? null)
      : null;

  const tracker = useJobTracker({
    fallbackJob,
    onFinish: (ev) => {
      if (ev.status === 'done') toast.success('Render terminado', 'Míralo en «Lección renderizada» y pásalo a Revisión.');
      else toast.error({ detail: ev.detail || 'El render falló' }, 'Render');
      lesson.refetch();
      lessons.refetch();
    },
  });
  const renderJob = tracker.job && tracker.job.params?.lesson_id === lessonId ? tracker.job : null;

  const open = (id) => {
    setSelected(0);
    setSp({ id: String(id) });
  };

  const lessonItems = lessons.data?.items ?? NO_ITEMS;

  return (
    <>
      <PageHeader
        title="Editor"
        subtitle="Arma la lección: orden, recortes, textos en pantalla y narración. Luego renderiza un vertical 9:16 de hasta 60 s."
        actions={
          <>
            <select
              aria-label="Abrir lección"
              className={`${selectCls} w-72`}
              value={lessonId ?? ''}
              onChange={(e) => (e.target.value ? open(e.target.value) : setSp({ nueva: '1' }))}
            >
              <option value="">{lessons.loading && !lessons.data ? 'Cargando lecciones…' : 'Abrir lección…'}</option>
              {lessonItems.map((l) => (
                <option key={l.id} value={l.id}>
                  #{l.id} · {l.title} ({LESSON_STATUS[l.status]?.label ?? l.status})
                </option>
              ))}
            </select>
            {!showNew && (
              <Button variant="accent" icon="add" onClick={() => setSp({ id: String(lessonId), nueva: '1' })}>
                Nueva
              </Button>
            )}
          </>
        }
      />

      {lessons.error && <ErrorBanner className="mb-4" error={lessons.error} onRetry={lessons.refetch} title="No se pudo cargar la lista de lecciones" />}

      {showNew && (
        <NewLessonForm
          key={sp.get('spec') ?? 'nueva'}
          vocab={vocab}
          initialSpec={sp.get('spec')}
          onCreated={(l) => {
            lessons.refetch();
            open(l.id);
          }}
          onCancel={lessonId ? () => setSp({ id: String(lessonId) }) : undefined}
        />
      )}

      {!lessonId && (
        <Card>
          <CardHeader title="Lecciones" icon="video_stable" subtitle="Abre una para editarla." />
          {lessons.loading && !lessons.data && <LoadingBlock />}
          {lessons.data && lessonItems.length === 0 && (
            <EmptyState icon="movie_edit" title="Aún no hay lecciones">
              Elige un tema arriba y pulsa «Armar».
            </EmptyState>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-3 p-4">
            {lessonItems.map((l) => (
              <button
                key={l.id}
                type="button"
                onClick={() => open(l.id)}
                className="text-left rounded-xl border border-outline-variant/15 bg-surface-low p-4 hover:border-primary/40 cursor-pointer transition-colors"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-bold">{l.title}</span>
                  <StatusPill map={LESSON_STATUS} status={l.status} />
                </div>
                <p className="text-[10px] text-on-surface-variant font-mono mt-1">{l.spec}</p>
                <p className="text-[10px] text-on-surface-variant mt-1">
                  {l.duration_s ? `${Number(l.duration_s).toFixed(1)} s · ` : ''}
                  {fmtDate(l.updated_at ?? l.created_at)}
                </p>
              </button>
            ))}
          </div>
        </Card>
      )}

      {lessonId && lesson.error && <ErrorBanner className="mb-4" error={lesson.error} onRetry={lesson.refetch} title={`No se pudo abrir la lección #${lessonId}`} />}
      {lessonId && !current && lesson.loading && <LoadingBlock label="Abriendo lección…" />}
      {current && (
        <LessonWorkspace
          key={`${current.id}:${current.updated_at}:${current.status}`}
          lesson={current}
          vocab={vocab}
          selected={selected}
          setSelected={setSelected}
          renderJob={renderJob}
          aiNotice={aiNotice?.lessonId === current.id ? aiNotice : null}
          onAiStatus={(detail) => setAiNotice(detail ? { lessonId: current.id, detail } : null)}
          onLessonChange={(updated) => {
            lesson.setData(updated);
            lessons.refetch();
          }}
          onRenderQueued={tracker.track}
          refetchLesson={lesson.refetch}
        />
      )}
    </>
  );
}
