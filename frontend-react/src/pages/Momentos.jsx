import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import AddToLessonModal from '../components/AddToLessonModal';
import MomentCard from '../components/MomentCard';
import SpecPicker from '../components/SpecPicker';
import { Button, Card, EmptyState, ErrorBanner, Field, Icon, LoadingBlock, Notice, PageHeader, Pill, Tabs } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useVocab } from '../hooks/useVocab';
import { fmtNumber, splitSpec } from '../lib/format';
import { DIMENSION_LABEL, MOMENT_STATUS } from '../lib/labels';
import { inputCls, selectCls } from '../lib/styles';

const PER_PAGE = 24;
const NO_ITEMS = [];

function useParamsState() {
  const [sp, setSp] = useSearchParams();
  const get = (k, fallback = '') => sp.get(k) ?? fallback;
  const update = (patch, { resetPage = true } = {}) => {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) {
      if (v === '' || v === null || v === undefined) next.delete(k);
      else next.set(k, String(v));
    }
    if (resetPage && !('page' in patch)) next.delete('page');
    setSp(next, { replace: true });
  };
  return { sp, get, update };
}

function MomentGrid({ items, vocab, onUpdated, onAddToLesson }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-4">
      {items.map((m) => (
        <MomentCard key={m.id} moment={m} vocab={vocab} onUpdated={onUpdated} onAddToLesson={onAddToLesson} />
      ))}
    </div>
  );
}

// ───────────────────────────── Explorar ─────────────────────────────

function Explorar({ params, vocab, onAddToLesson }) {
  const { get, update } = params;
  const works = useApi((signal) => api.works({ signal }), []);
  const filters = {
    asset_id: get('asset_id'),
    work_id: get('work_id'),
    dimension: get('dimension'),
    value: get('value'),
    min_conf: get('min_conf'),
    status: get('status'),
    q: get('q'),
    page: Number(get('page', '1')) || 1,
    per_page: PER_PAGE,
  };
  const moments = useApi((signal) => api.moments(filters, { signal }), [filters]);
  const total = moments.data?.total ?? 0;
  const page = moments.data?.page ?? filters.page;
  const pages = Math.max(1, Math.ceil(total / (moments.data?.per_page ?? PER_PAGE)));
  const items = moments.data?.items ?? NO_ITEMS;

  const onUpdated = (u) =>
    moments.setData((prev) => (prev ? { ...prev, items: prev.items.map((m) => (m.id === u.id ? { ...m, ...u } : m)) } : prev));

  const onSearch = (e) => {
    e.preventDefault();
    update({ q: new FormData(e.currentTarget).get('q')?.toString().trim() ?? '' });
  };

  return (
    <>
      <Card className="p-4 mb-6">
        <div className="grid grid-cols-12 gap-3 items-end">
          <Field label="Etiqueta" className="col-span-12 lg:col-span-4">
            <SpecPicker
              vocab={vocab}
              allowAnyDimension
              dimension={filters.dimension}
              value={filters.value}
              onChange={({ dimension, value }) => update({ dimension, value })}
              idPrefix="filtro"
            />
          </Field>
          <Field label="Obra" className="col-span-6 lg:col-span-3">
            {(id) => (
              <select id={id} className={selectCls} value={filters.work_id} onChange={(e) => update({ work_id: e.target.value, asset_id: '' })}>
                <option value="">Todas las obras</option>
                {(works.data?.items ?? NO_ITEMS).map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.title} ({w.year ?? 's. f.'})
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Estado" className="col-span-6 lg:col-span-2">
            {(id) => (
              <select id={id} className={selectCls} value={filters.status} onChange={(e) => update({ status: e.target.value })}>
                <option value="">Todos</option>
                {Object.entries(MOMENT_STATUS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v.label}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label="Confianza" className="col-span-6 lg:col-span-1" hint={filters.value ? undefined : 'Elige etiqueta'}>
            {(id) => (
              <select
                id={id}
                className={selectCls}
                value={filters.min_conf}
                disabled={!filters.value}
                onChange={(e) => update({ min_conf: e.target.value })}
              >
                <option value="">0</option>
                {['0.3', '0.5', '0.7', '0.9'].map((v) => (
                  <option key={v} value={v}>
                    {v}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <form onSubmit={onSearch} className="col-span-6 lg:col-span-2">
            <Field label="Texto">
              {(id) => (
                <div className="flex gap-1">
                  <input id={id} key={filters.q} name="q" defaultValue={filters.q} placeholder="frase, cita…" className={inputCls} />
                  <Button type="submit" size="sm" variant="ghost" icon="search" aria-label="Buscar texto" />
                </div>
              )}
            </Field>
          </form>
        </div>
        {(filters.asset_id || filters.work_id || filters.value || filters.status || filters.q) && (
          <div className="flex flex-wrap items-center gap-2 mt-3">
            {filters.asset_id && <Pill tone="info">Asset #{filters.asset_id}</Pill>}
            <button
              type="button"
              className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant hover:text-on-surface cursor-pointer"
              onClick={() => update({ asset_id: '', work_id: '', dimension: '', value: '', min_conf: '', status: '', q: '' })}
            >
              Limpiar filtros
            </button>
          </div>
        )}
      </Card>

      {moments.error && <ErrorBanner className="mb-4" error={moments.error} onRetry={moments.refetch} title="No se pudieron cargar los momentos" />}
      {moments.loading && !moments.data && <LoadingBlock label="Cargando momentos…" />}
      {moments.data && items.length === 0 && (
        <EmptyState icon="movie_filter" title="No hay momentos con esos filtros">
          Si la obra es nueva, en la <Link to="/biblioteca" className="text-primary underline">Biblioteca</Link> indexa → detecta → etiqueta.
        </EmptyState>
      )}

      {items.length > 0 && (
        <>
          <div className="flex items-center justify-between mb-3 text-xs text-on-surface-variant">
            <span>
              {fmtNumber(total)} momentos · ordenados por importancia
              {moments.loading && <span className="ml-2 text-primary">actualizando…</span>}
            </span>
          </div>
          <MomentGrid items={items} vocab={vocab} onUpdated={onUpdated} onAddToLesson={onAddToLesson} />
          <div className="flex items-center justify-center gap-3 mt-6">
            <Button size="sm" variant="ghost" icon="chevron_left" disabled={page <= 1 || moments.loading} onClick={() => update({ page: page - 1 }, { resetPage: false })}>
              Anterior
            </Button>
            <span className="text-xs text-on-surface-variant font-mono">
              Página {page} de {pages}
            </span>
            <Button size="sm" variant="ghost" disabled={page >= pages || moments.loading} onClick={() => update({ page: page + 1 }, { resetPage: false })}>
              Siguiente
              <Icon name="chevron_right" className="text-sm" />
            </Button>
          </div>
        </>
      )}
    </>
  );
}

// ───────────────────────────── Buscar entre obras ─────────────────────────────

function BuscarEntreObras({ params, vocab, onAddToLesson }) {
  const { get, update } = params;
  const spec = get('spec');
  const [specDim, specVal] = splitSpec(spec);
  const query = {
    spec,
    limit: Number(get('limit', '6')) || 6,
    min_works: Number(get('min_works', '3')) || 3,
    per_work: Number(get('per_work', '1')) || 1,
    min_confidence: Number(get('min_confidence', '0.5')),
  };
  const [draft, setDraft] = useState({
    dimension: specDim || 'emotion',
    value: specVal || '',
    limit: query.limit,
    min_works: query.min_works,
    per_work: query.per_work,
    min_confidence: query.min_confidence,
  });
  const result = useApi((signal) => api.findMoments(query, { signal }), [query], { enabled: Boolean(spec) });
  const items = result.data?.items ?? NO_ITEMS;

  const onUpdated = (u) =>
    result.setData((prev) => (prev ? { ...prev, items: prev.items.map((m) => (m.id === u.id ? { ...m, ...u } : m)) } : prev));

  const submit = (e) => {
    e.preventDefault();
    if (!draft.value) return;
    const next = {
      spec: `${draft.dimension}:${draft.value}`,
      limit: Number(draft.limit) || 6,
      min_works: Number(draft.min_works) || 3,
      per_work: Number(draft.per_work) || 1,
      min_confidence: Number(draft.min_confidence) || 0,
    };
    // Si nada cambió, la URL no cambia: repetimos la búsqueda a mano.
    if (JSON.stringify(next) === JSON.stringify(query)) result.refetch();
    else update(next);
  };

  const numberInput = (key, { min, max, step = 1 }) => (
    <input
      type="number"
      min={min}
      max={max}
      step={step}
      value={draft[key]}
      onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
      className={`${inputCls} font-mono`}
    />
  );

  return (
    <>
      <Card className="p-4 mb-6">
        <form onSubmit={submit} className="grid grid-cols-12 gap-3 items-end">
          <Field label="Tema (emoción, tropo…)" className="col-span-12 lg:col-span-5">
            <SpecPicker
              vocab={vocab}
              dimension={draft.dimension}
              value={draft.value}
              onChange={(v) => setDraft((d) => ({ ...d, ...v }))}
              idPrefix="buscar"
              required
            />
          </Field>
          <Field label="Momentos" className="col-span-3 lg:col-span-1">
            {numberInput('limit', { min: 1, max: 30 })}
          </Field>
          <Field label="Obras mín." className="col-span-3 lg:col-span-1">
            {numberInput('min_works', { min: 1, max: 10 })}
          </Field>
          <Field label="Por obra" className="col-span-3 lg:col-span-1">
            {numberInput('per_work', { min: 1, max: 5 })}
          </Field>
          <Field label="Confianza" className="col-span-3 lg:col-span-1">
            {numberInput('min_confidence', { min: 0, max: 1, step: 0.05 })}
          </Field>
          <div className="col-span-12 lg:col-span-3 flex gap-2">
            <Button type="submit" variant="primary" icon="hub" className="flex-1" disabled={!draft.value} loading={result.loading}>
              Buscar entre obras
            </Button>
          </div>
        </form>
      </Card>

      {!spec && (
        <EmptyState icon="hub" title="Elige un tema">
          Encuentra el mismo sentimiento o tropo en películas distintas: es la base de una lección.
        </EmptyState>
      )}
      {result.error && <ErrorBanner className="mb-4" error={result.error} onRetry={result.refetch} title="La búsqueda falló" />}
      {result.loading && !result.data && <LoadingBlock label="Buscando entre obras…" />}

      {spec && result.data && (
        <>
          <div className="flex flex-wrap items-center gap-3 mb-4">
            <Pill tone="info" icon="label">
              {DIMENSION_LABEL[result.data.dimension] ?? result.data.dimension}: {vocab.labelOf(result.data.dimension, result.data.value)}
            </Pill>
            <span className="text-xs text-on-surface-variant">
              <b className="text-on-surface">{result.data.distinct_works}</b> obras distintas ·{' '}
              <b className="text-on-surface">{fmtNumber(result.data.candidates)}</b> candidatos
            </span>
            <Link
              to={`/editor?nueva=1&spec=${encodeURIComponent(spec)}`}
              className="ml-auto font-headline text-[10px] font-bold uppercase tracking-wider px-3 py-1.5 rounded-lg bg-primary-glow/10 text-primary-glow hover:bg-primary-glow/20 flex items-center gap-1"
            >
              <Icon name="movie_edit" className="text-sm" />
              Armar lección con este tema
            </Link>
          </div>
          {result.data.warning && <Notice className="mb-4">{result.data.warning}</Notice>}
          {items.length === 0 ? (
            <EmptyState icon="search_off" title="Ningún momento con ese tema">
              Etiqueta más obras o baja la confianza mínima.
            </EmptyState>
          ) : (
            <MomentGrid items={items} vocab={vocab} onUpdated={onUpdated} onAddToLesson={onAddToLesson} />
          )}
        </>
      )}
    </>
  );
}

export default function Momentos() {
  const params = useParamsState();
  const vocab = useVocab();
  const [target, setTarget] = useState(null);
  const tab = params.get('tab', 'explorar');

  return (
    <>
      <PageHeader
        title="Momentos"
        subtitle="Escenas clave detectadas en cada película. Revisa por qué se eligieron, corrige etiquetas y súmalas a una lección."
        actions={
          <Tabs
            value={tab}
            onChange={(id) => params.update({ tab: id === 'explorar' ? '' : id })}
            tabs={[
              { id: 'explorar', label: 'Explorar', icon: 'grid_view' },
              { id: 'buscar', label: 'Buscar entre obras', icon: 'hub' },
            ]}
          />
        }
      />
      {vocab.error && <ErrorBanner className="mb-4" error={vocab.error} onRetry={vocab.refetch} title="No se pudo cargar el vocabulario" />}

      {tab === 'buscar' ? (
        <BuscarEntreObras params={params} vocab={vocab} onAddToLesson={setTarget} />
      ) : (
        <Explorar params={params} vocab={vocab} onAddToLesson={setTarget} />
      )}

      <AddToLessonModal key={target?.id ?? 'none'} moment={target} onClose={() => setTarget(null)} />
    </>
  );
}
