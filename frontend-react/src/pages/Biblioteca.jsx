import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { Button, Card, CardHeader, EmptyState, ErrorBanner, Field, Icon, LoadingBlock, Notice, PageHeader, Pill, ProgressBar, StatusPill } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useDebouncedCallback } from '../hooks/useDebounced';
import { useLiveJobs } from '../hooks/useJobsSocket';
import { useToast } from '../hooks/useToast';
import { fmtLongDuration, fmtNumber } from '../lib/format';
import { isTerminal, jobPct, jobTouchesAsset } from '../lib/jobs';
import { INDEX_STEPS, JOB_STATUS, JOB_TYPE, PROVIDERS, rightsInfo } from '../lib/labels';
import { checkboxCls, inputCls } from '../lib/styles';

const NO_ITEMS = [];
// Mientras carga /media/providers (o si falla) se busca en las dos fuentes de siempre.
const FALLBACK_PROVIDERS = [
  { name: 'archive_org', available: true },
  { name: 'local', available: true },
];
const LIBRARY_JOBS = new Set(['index', 'detect', 'label']);
const candidateKey = (c) => `${c.provider}:${c.external_id}`;

// ───────────────────────────── Búsqueda ─────────────────────────────

function CandidateCard({ candidate, registered, registering, onRegister }) {
  const rights = rightsInfo(candidate.rights);
  const usable = candidate.usable ?? rights.usable;
  return (
    <div className={`rounded-xl border p-4 flex flex-col gap-3 ${usable ? 'border-outline-variant/15 bg-surface-low' : 'border-outline-variant/10 bg-surface-low/50'}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h4 className="text-sm font-bold leading-tight">
            {candidate.title} <span className="text-on-surface-variant font-normal">({candidate.year ?? 's. f.'})</span>
          </h4>
          <p className="text-[10px] text-on-surface-variant font-mono truncate mt-0.5" title={candidate.external_id}>
            {PROVIDERS[candidate.provider] ?? candidate.provider} · {candidate.external_id}
          </p>
          {candidate.via && (
            <p className="text-[10px] text-on-surface-variant mt-0.5 flex items-center gap-1">
              <Icon name="extension" className="text-[11px]" />
              Encontrado con tu addon de Stremio
            </p>
          )}
        </div>
        <Pill tone={rights.tone} icon={usable ? 'verified' : 'gpp_maybe'}>
          {rights.label}
        </Pill>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-on-surface-variant">
        {candidate.height && <span>{candidate.height}p</span>}
        {candidate.duration_ms ? <span>{fmtLongDuration(candidate.duration_ms)}</span> : null}
        {candidate.master_file && <span className="font-mono truncate max-w-full" title="Archivo maestro">{candidate.master_file}</span>}
        {candidate.license_url && (
          <a href={candidate.license_url} target="_blank" rel="noreferrer" className="text-primary hover:underline flex items-center gap-0.5">
            Licencia <Icon name="open_in_new" className="text-[11px]" />
          </a>
        )}
      </div>

      {candidate.partial && (
        <Notice tone="warn" icon="content_cut">
          Archivo parcial: el maestro dura bastante menos que la película. Puede faltar el final.
        </Notice>
      )}
      {!usable && (
        <Notice tone={rights.tone === 'error' ? 'error' : 'warn'} icon="gavel">
          {rights.explain ?? 'Los derechos de este archivo no permiten producir con él.'}
        </Notice>
      )}

      <div className="mt-auto flex justify-end">
        {registered ? (
          <Pill tone="ok" icon="check">En la biblioteca</Pill>
        ) : (
          <Button
            size="sm"
            variant={usable ? 'accent' : 'subtle'}
            icon="library_add"
            disabled={!usable}
            loading={registering}
            title={usable ? undefined : 'Solo se registran archivos con derechos usables'}
            onClick={() => onRegister(candidate)}
          >
            Registrar
          </Button>
        )}
      </div>
    </div>
  );
}

function MediaSearch({ registeredKeys, onRegistered }) {
  const toast = useToast();
  const providerInfo = useApi((signal) => api.mediaProviders({ signal }), []);
  const [form, setForm] = useState({ title: '', year: '', allRights: false });
  const [picked, setPicked] = useState({});
  const [results, setResults] = useState({ items: null, warnings: NO_ITEMS, loading: false, error: null });
  const [registering, setRegistering] = useState(null);

  const sources = providerInfo.data?.items ?? FALLBACK_PROVIDERS;
  const providers = sources.filter((p) => p.available && (picked[p.name] ?? true)).map((p) => p.name);
  const canSearch = form.title.trim().length > 1 && providers.length > 0 && !results.loading;

  const search = async (e) => {
    e.preventDefault();
    if (!canSearch) return;
    const yearNum = Number(form.year);
    const body = { title: form.title.trim(), providers, all_rights: form.allRights };
    if (form.year && Number.isInteger(yearNum)) body.year = yearNum;
    setResults((r) => ({ ...r, loading: true, error: null }));
    try {
      const res = await api.searchMedia(body);
      setResults({ items: res.items ?? [], warnings: res.warnings ?? NO_ITEMS, loading: false, error: null });
    } catch (err) {
      setResults({ items: null, warnings: NO_ITEMS, loading: false, error: err });
    }
  };

  const register = async (c) => {
    setRegistering(candidateKey(c));
    try {
      const asset = await api.ingest({ provider: c.provider, external_id: c.external_id, title: c.title, year: c.year ?? undefined });
      toast.success(`Registrado: ${c.title}`, 'Ahora puedes indexarlo desde la lista de obras.');
      onRegistered(asset);
    } catch (err) {
      toast.error(err, 'No se pudo registrar');
    } finally {
      setRegistering(null);
    }
  };

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));

  return (
    <Card className="mb-6">
      <CardHeader
        title="Buscar películas"
        icon="travel_explore"
        subtitle="Internet Archive, tu biblioteca local y tu addon de Stremio. Solo se registran obras de dominio público, licencia abierta o propias."
      />
      <form onSubmit={search} className="p-4 grid grid-cols-12 gap-3 items-end">
        <Field label="Título" className="col-span-12 md:col-span-5">
          {(id) => (
            <input id={id} className={inputCls} value={form.title} placeholder="Night of the Living Dead" onChange={(e) => set({ title: e.target.value })} />
          )}
        </Field>
        <Field label="Año" className="col-span-4 md:col-span-2">
          {(id) => (
            <input id={id} className={inputCls} inputMode="numeric" value={form.year} placeholder="1968" onChange={(e) => set({ year: e.target.value.replace(/\D/g, '').slice(0, 4) })} />
          )}
        </Field>
        <fieldset className="col-span-8 md:col-span-3 flex flex-wrap gap-x-4 gap-y-1 text-xs pb-2">
          <legend className="sr-only">Fuentes</legend>
          {sources.map((p) => (
            <label
              key={p.name}
              className={`flex items-center gap-1.5 ${p.available ? 'cursor-pointer' : 'cursor-not-allowed opacity-50'}`}
              title={p.detail}
            >
              <input
                type="checkbox"
                className={checkboxCls}
                disabled={!p.available}
                checked={p.available && (picked[p.name] ?? true)}
                onChange={(e) => setPicked((s) => ({ ...s, [p.name]: e.target.checked }))}
              />
              {PROVIDERS[p.name] ?? p.name}
            </label>
          ))}
          <label className="flex items-center gap-1.5 cursor-pointer" title="Muestra también resultados sin derechos usables (no se pueden registrar)">
            <input type="checkbox" className={checkboxCls} checked={form.allRights} onChange={(e) => set({ allRights: e.target.checked })} />
            Ver todos los derechos
          </label>
        </fieldset>
        <div className="col-span-12 md:col-span-2">
          <Button type="submit" variant="primary" icon="search" className="w-full" loading={results.loading} disabled={!canSearch}>
            Buscar
          </Button>
        </div>
      </form>

      <div className="px-4 pb-4">
        {results.error && <ErrorBanner error={results.error} title="La búsqueda falló" />}
        {!results.loading && results.warnings.length > 0 && (
          <Notice tone="warn" icon="cloud_off" className="mb-3">
            Algunas fuentes no respondieron y se saltaron: {results.warnings.join(' · ')}
          </Notice>
        )}
        {results.loading && <LoadingBlock label="Buscando en las fuentes…" />}
        {!results.loading && results.items && results.items.length === 0 && (
          <EmptyState icon="search_off" title="Sin resultados">
            Prueba con el título original en inglés o sin año.
          </EmptyState>
        )}
        {!results.loading && results.items && results.items.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-3">
            {results.items.map((c) => (
              <CandidateCard
                key={candidateKey(c)}
                candidate={c}
                registered={registeredKeys.has(candidateKey(c))}
                registering={registering === candidateKey(c)}
                onRegister={register}
              />
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

// ───────────────────────────── Biblioteca ─────────────────────────────

function StepChips({ steps }) {
  return (
    <div className="flex flex-wrap gap-1">
      {INDEX_STEPS.map((s) => {
        const done = Boolean(steps?.[s.id]);
        return (
          <span
            key={s.id}
            title={`${s.hint}: ${done ? 'listo' : 'pendiente'}`}
            className={`inline-flex items-center gap-0.5 text-[10px] px-1.5 py-0.5 rounded ${done ? 'bg-tertiary/15 text-tertiary' : 'bg-surface-highest text-on-surface-variant'}`}
          >
            <Icon name={done ? 'check' : 'radio_button_unchecked'} className="text-[11px]" />
            {s.label}
          </span>
        );
      })}
    </div>
  );
}

function AssetJob({ job }) {
  if (!job) return null;
  const type = JOB_TYPE[job.type]?.label ?? job.type;
  if (job.status === 'error') {
    return (
      <p className="text-[10px] text-error flex items-center gap-1" title={job.error ?? ''}>
        <Icon name="error" className="text-xs" />
        {type} falló (#{job.id}).{' '}
        <Link to="/trabajos" className="underline">Ver detalle</Link>
      </p>
    );
  }
  if (isTerminal(job.status)) return null;
  const pct = jobPct(job);
  return (
    <div className="flex items-center gap-2 min-w-48">
      <StatusPill map={JOB_STATUS} status={job.status} />
      <span className="text-[10px] text-on-surface-variant whitespace-nowrap">{type}</span>
      <ProgressBar value={pct ?? 0} indeterminate={pct === null} className="w-24" />
      {job.progress?.stage && <span className="text-[10px] font-mono text-on-surface-variant whitespace-nowrap">{job.progress.stage}</span>}
    </div>
  );
}

function AssetRow({ asset, job, selected, onSelect, onQueue, queueing }) {
  const rights = rightsInfo(asset.rights);
  const busy = job && !isTerminal(job.status);
  const moments = asset.moments ?? 0;
  return (
    <div className="px-4 py-3 flex flex-wrap items-center gap-x-4 gap-y-2">
      <input type="checkbox" className={checkboxCls} checked={selected} onChange={(e) => onSelect(asset.id, e.target.checked)} aria-label={`Seleccionar asset ${asset.id}`} />
      <div className="min-w-56 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-bold">#{asset.id}</span>
          <span className="text-[10px] text-on-surface-variant">{PROVIDERS[asset.provider] ?? asset.provider}</span>
          <Pill tone={rights.tone}>{rights.label}</Pill>
          {asset.accept_ranges === false && <Pill tone="warn" title="El servidor no acepta rangos: cada corte descarga más">Sin rangos</Pill>}
        </div>
        <p className="text-[10px] font-mono text-on-surface-variant truncate mt-0.5" title={asset.external_id}>{asset.external_id}</p>
        <p className="text-[10px] text-on-surface-variant mt-0.5">
          {fmtLongDuration(asset.duration_ms)}
          {asset.height ? ` · ${asset.height}p` : ''}
          {asset.fps ? ` · ${Number(asset.fps).toFixed(2)} fps` : ''}
        </p>
      </div>
      <StepChips steps={asset.steps} />
      <Link
        to={`/momentos?asset_id=${asset.id}`}
        className="text-[11px] text-on-surface-variant hover:text-primary"
        title="Ver momentos de este asset"
      >
        <span className="font-bold text-on-surface">{fmtNumber(moments)}</span> momentos ·{' '}
        <span className="font-bold text-on-surface">{fmtNumber(asset.moments_labeled ?? 0)}</span> etiquetados
      </Link>
      <div className="flex flex-wrap items-center gap-2 ml-auto">
        <AssetJob job={job} />
        <Button size="xs" variant="subtle" icon="manage_search" disabled={busy} loading={queueing === `index:${asset.id}`} onClick={() => onQueue('index', asset)}>
          Indexar
        </Button>
        <Button
          size="xs"
          variant="subtle"
          icon="movie_filter"
          disabled={busy || !asset.steps?.asr}
          title={asset.steps?.asr ? undefined : 'Primero indexa (necesita la transcripción)'}
          loading={queueing === `detect:${asset.id}`}
          onClick={() => onQueue('detect', asset)}
        >
          Detectar
        </Button>
        <Button
          size="xs"
          variant="subtle"
          icon="label"
          disabled={busy || moments === 0}
          title={moments === 0 ? 'Primero detecta momentos' : undefined}
          loading={queueing === `label:${asset.id}`}
          onClick={() => onQueue('label', asset)}
        >
          Etiquetar
        </Button>
      </div>
    </div>
  );
}

export default function Biblioteca() {
  const toast = useToast();
  const works = useApi((signal) => api.works({ signal }), []);
  const assets = useApi((signal) => api.assets({}, { signal }), []);
  const jobList = useApi((signal) => api.jobs({ limit: 100 }, { signal }), []);

  const [selected, setSelected] = useState(() => new Set());
  const [opts, setOpts] = useState({ force: false, fetchAnchors: true, topK: 40 });
  const [queueing, setQueueing] = useState(null);

  const refreshLibrary = useDebouncedCallback(() => {
    works.refetch();
    assets.refetch();
  }, 1000);
  const refreshJobs = useDebouncedCallback(jobList.refetch, 1000);
  const { jobs } = useLiveJobs(jobList.data?.items ?? NO_ITEMS, {
    onUnknown: refreshJobs,
    onFinish: (ev) => {
      if (LIBRARY_JOBS.has(ev.type)) refreshLibrary();
    },
  });

  const assetItems = assets.data?.items ?? NO_ITEMS;
  const assetsByWork = useMemo(() => {
    const map = new Map();
    for (const a of assetItems) {
      if (!map.has(a.work_id)) map.set(a.work_id, []);
      map.get(a.work_id).push(a);
    }
    return map;
  }, [assetItems]);

  const registeredKeys = useMemo(() => new Set(assetItems.map((a) => `${a.provider}:${a.external_id}`)), [assetItems]);

  const latestJobFor = (assetId) => {
    const related = jobs.filter((j) => LIBRARY_JOBS.has(j.type) && jobTouchesAsset(j, assetId));
    return related.find((j) => !isTerminal(j.status)) ?? related.sort((a, b) => b.id - a.id)[0] ?? null;
  };

  const queue = async (type, assetIds) => {
    const params =
      type === 'index'
        ? { asset_ids: assetIds, force: opts.force }
        : type === 'detect'
          ? { asset_id: assetIds[0], fetch_anchors: opts.fetchAnchors }
          : { asset_id: assetIds[0], top_k: opts.topK, provider: null };
    setQueueing(assetIds.length === 1 ? `${type}:${assetIds[0]}` : `${type}:bulk`);
    try {
      const job = await api.createJob(type, params);
      jobList.setData((prev) => ({ ...(prev ?? {}), items: [job, ...(prev?.items ?? [])] }));
      toast.success(`Trabajo #${job.id} en cola: ${JOB_TYPE[type]?.label ?? type}`, 'Sigue el progreso aquí o en Trabajos.');
      return true;
    } catch (err) {
      toast.error(err, `No se pudo encolar «${JOB_TYPE[type]?.label ?? type}»`);
      return false;
    } finally {
      setQueueing(null);
    }
  };

  const onSelect = (id, checked) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });

  const indexSelected = async () => {
    const ok = await queue('index', [...selected]);
    if (ok) setSelected(new Set());
  };

  const loadError = works.error || assets.error;
  const workItems = works.data?.items ?? NO_ITEMS;

  return (
    <>
      <PageHeader
        title="Biblioteca"
        subtitle="Busca películas con derechos claros, regístralas y prepáralas: indexar (audio, transcripción, planos) → detectar momentos → etiquetar."
      />

      <MediaSearch registeredKeys={registeredKeys} onRegistered={() => refreshLibrary()} />

      <Card>
        <CardHeader
          title="Obras registradas"
          icon="video_library"
          subtitle={works.data ? `${workItems.length} obras · ${assetItems.length} assets` : undefined}
          actions={
            <Button size="sm" variant="ghost" icon="refresh" loading={works.loading || assets.loading} onClick={refreshLibrary}>
              Actualizar
            </Button>
          }
        />

        <div className="px-4 py-3 border-b border-outline-variant/10 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs bg-surface-low/50">
          <span className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">Opciones</span>
          <label className="flex items-center gap-1.5 cursor-pointer" title="Rehace los pasos aunque ya estén listos">
            <input type="checkbox" className={checkboxCls} checked={opts.force} onChange={(e) => setOpts((o) => ({ ...o, force: e.target.checked }))} />
            Forzar reindexado
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer" title="Busca citas célebres y resúmenes de trama para anclar momentos">
            <input type="checkbox" className={checkboxCls} checked={opts.fetchAnchors} onChange={(e) => setOpts((o) => ({ ...o, fetchAnchors: e.target.checked }))} />
            Buscar anclas (citas/trama) al detectar
          </label>
          <label className="flex items-center gap-1.5">
            Etiquetar los
            <input
              type="number"
              min={1}
              max={200}
              value={opts.topK}
              onChange={(e) => setOpts((o) => ({ ...o, topK: Math.max(1, Math.min(200, Number(e.target.value) || 40)) }))}
              className="w-16 bg-surface-highest rounded-md px-2 py-1 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-primary"
            />
            más importantes
          </label>
          <div className="ml-auto flex items-center gap-2">
            {selected.size > 0 && <span className="text-[11px] text-on-surface-variant">{selected.size} seleccionados</span>}
            <Button size="sm" variant="accent" icon="manage_search" disabled={selected.size === 0} loading={queueing === 'index:bulk'} onClick={indexSelected}>
              Indexar seleccionados
            </Button>
          </div>
        </div>

        {loadError && <ErrorBanner className="m-4" error={loadError} onRetry={refreshLibrary} title="No se pudo cargar la biblioteca" />}
        {(works.loading || assets.loading) && !works.data && <LoadingBlock label="Cargando obras…" />}
        {works.data && workItems.length === 0 && (
          <EmptyState icon="movie" title="La biblioteca está vacía">
            Busca una película arriba y regístrala para empezar.
          </EmptyState>
        )}

        <div className="divide-y divide-outline-variant/10">
          {workItems.map((w) => {
            const list = assetsByWork.get(w.id) ?? NO_ITEMS;
            return (
              <div key={w.id}>
                <div className="px-4 py-2.5 bg-surface-low/60 flex items-center gap-3">
                  <Icon name={w.kind === 'movie' ? 'movie' : 'live_tv'} className="text-sm text-primary" />
                  <span className="text-sm font-bold">{w.title}</span>
                  <span className="text-xs text-on-surface-variant">{w.year ?? 's. f.'}</span>
                  <Link to={`/momentos?work_id=${w.id}`} className="ml-auto text-[10px] font-bold uppercase tracking-widest text-primary hover:underline">
                    Momentos
                  </Link>
                </div>
                {list.length === 0 && <p className="px-4 py-3 text-[11px] text-on-surface-variant">Sin assets.</p>}
                <div className="divide-y divide-outline-variant/5">
                  {list.map((a) => (
                    <AssetRow
                      key={a.id}
                      asset={a}
                      job={latestJobFor(a.id)}
                      selected={selected.has(a.id)}
                      onSelect={onSelect}
                      onQueue={(type, asset) => queue(type, [asset.id])}
                      queueing={queueing}
                    />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
        {jobList.error && (
          <p className="px-4 py-2 text-[10px] text-amber-300">No se pudo leer la cola de trabajos: el progreso por asset puede no aparecer.</p>
        )}
      </Card>
    </>
  );
}
