import { Link } from 'react-router-dom';
import { YOUTUBE_CONNECT_URL, api } from '../api/client';
import JobRow from '../components/JobRow';
import { Button, Card, CardHeader, EmptyState, ErrorBanner, Icon, LoadingBlock, PageHeader, Pill, ProgressBar, Spinner, Stat } from '../components/ui';
import { useApi } from '../hooks/useApi';
import { useDebouncedCallback } from '../hooks/useDebounced';
import { useLiveJobs } from '../hooks/useJobsSocket';
import { fmtGB, fmtNumber } from '../lib/format';
import { CREDENTIAL_TONE, LESSON_STATUS, STORAGE_LABELS, humanize } from '../lib/labels';

const NO_JOBS = [];
const NO_ACCOUNTS = [];
const LINK_CLS = 'text-[10px] font-bold uppercase tracking-widest text-primary hover:underline flex items-center gap-1';

function AccountRow({ platform, icon, children }) {
  return (
    <li className="flex items-center justify-between gap-3 bg-surface-low rounded-lg px-3 py-2.5">
      <span className="flex items-center gap-2 text-xs font-bold">
        <Icon name={icon} className="text-sm text-primary" />
        {platform}
      </span>
      <span className="flex items-center gap-2 min-w-0 justify-end flex-wrap">{children}</span>
    </li>
  );
}

/**
 * Solo nombres visibles: el open_id y los tokens de TikTok se quedan en el sitio (Railway);
 * el de YouTube, cifrado en tokens/. Se consulta aparte del resumen para no frenarlo si el puente tarda.
 */
function AccountsCard({ webBaseUrl }) {
  const tiktok = useApi((signal) => api.tiktokAccounts({ signal }), []);
  const youtube = useApi((signal) => api.youtubeStatus({ signal }), []);
  const accounts = tiktok.data?.accounts ?? NO_ACCOUNTS;
  const connectTikTok = webBaseUrl ? `${webBaseUrl.replace(/\/+$/, '')}/studio` : null;
  const refetchAll = () => {
    tiktok.refetch();
    youtube.refetch();
  };

  return (
    <Card>
      <CardHeader
        title="Cuentas conectadas"
        icon="link"
        subtitle="Solo se muestra el nombre; los tokens no salen del sitio público (TikTok) ni del archivo cifrado (YouTube)."
        actions={
          <Button variant="ghost" icon="refresh" loading={tiktok.loading || youtube.loading} onClick={refetchAll}>
            Actualizar
          </Button>
        }
      />
      <ul className="p-4 space-y-2">
        <AccountRow platform="TikTok" icon="music_video">
          {tiktok.loading && !tiktok.data && <Spinner />}
          {tiktok.error && (
            <Pill tone="error" icon="cloud_off" title={tiktok.error.detail}>
              Sitio sin respuesta
            </Pill>
          )}
          {accounts.map((a) => (
            <Pill key={a.open_id} tone="ok" icon="check_circle">
              {a.display_name || 'Cuenta sin nombre'}
            </Pill>
          ))}
          {tiktok.data && accounts.length === 0 && (
            <>
              <Pill tone="warn">Sin conectar</Pill>
              {connectTikTok && (
                <a href={connectTikTok} target="_blank" rel="noreferrer" className={LINK_CLS}>
                  Conectar <Icon name="open_in_new" className="text-xs" />
                </a>
              )}
            </>
          )}
        </AccountRow>
        <AccountRow platform="YouTube" icon="smart_display">
          {youtube.loading && !youtube.data && <Spinner />}
          {youtube.error && <Pill tone="error">Error al leer</Pill>}
          {youtube.data?.connected && !youtube.data.warning && (
            <Pill tone="ok" icon="check_circle">
              {youtube.data.channel_title || 'Canal conectado'}
            </Pill>
          )}
          {youtube.data?.connected && youtube.data.warning && (
            <Pill tone="warn" icon="warning" title={youtube.data.warning}>Falta un paso (ver Revisión)</Pill>
          )}
          {youtube.data && !youtube.data.connected && (
            <>
              <Pill tone="warn">Sin conectar</Pill>
              <a href={YOUTUBE_CONNECT_URL} target="_blank" rel="noreferrer" className={LINK_CLS}>
                Conectar <Icon name="open_in_new" className="text-xs" />
              </a>
            </>
          )}
        </AccountRow>
      </ul>
    </Card>
  );
}

function StorageRow({ name, layer }) {
  const cap = layer.cap_gb;
  const used = layer.gb ?? 0;
  const pct = cap ? (used / cap) * 100 : null;
  const count = layer.files ?? layer.assets;
  const countLabel = layer.files !== undefined ? 'archivos' : 'assets';
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="font-bold">{STORAGE_LABELS[name] ?? humanize(name)}</span>
        <span className="font-mono text-on-surface-variant">
          {fmtGB(used)}
          {cap ? ` / ${fmtGB(cap)}` : ''}
        </span>
      </div>
      {pct !== null && (
        <ProgressBar className="mt-1.5" value={pct} tone={pct > 90 ? 'error' : pct > 70 ? 'warn' : 'ok'} />
      )}
      {count !== undefined && (
        <p className="text-[10px] text-on-surface-variant mt-1">
          {fmtNumber(count)} {countLabel}
          {pct !== null && ` · ${Math.round(pct)} % del tope`}
        </p>
      )}
    </div>
  );
}

function SettingRow({ label, value, href }) {
  return (
    <div className="flex items-center justify-between gap-3 py-2 text-xs border-b border-outline-variant/10 last:border-0">
      <span className="text-on-surface-variant">{label}</span>
      {href && value ? (
        <a href={href} target="_blank" rel="noreferrer" className="font-mono text-primary hover:underline min-w-0 flex items-center gap-1">
          <span className="truncate">{value}</span>
          <Icon name="open_in_new" className="text-xs flex-shrink-0" />
        </a>
      ) : (
        <span className="font-mono truncate">{value || <span className="text-on-surface-variant">sin definir</span>}</span>
      )}
    </div>
  );
}

export default function Inicio() {
  const overview = useApi((signal) => api.overview({ signal }), []);
  const refresh = useDebouncedCallback(overview.refetch, 1500);
  const { jobs } = useLiveJobs(overview.data?.jobs ?? NO_JOBS, { onUnknown: refresh, onFinish: refresh });

  const data = overview.data;
  const counts = data?.counts ?? {};
  const lessonCounts = counts.lessons ?? {};
  const storage = data?.storage ?? {};
  const storageLayers = Object.entries(storage).filter(([, v]) => v && typeof v === 'object');
  const settings = data?.settings ?? {};

  return (
    <>
      <PageHeader
        title="Inicio"
        subtitle="Estado del estudio: qué hay indexado, cuánto ocupa, qué credenciales están listas y qué trabajos corren ahora."
        actions={
          <>
            <Link to="/biblioteca" className="font-headline text-xs font-bold uppercase tracking-wider px-4 py-2 rounded-lg bg-surface-highest hover:bg-surface-bright flex items-center gap-1.5">
              <Icon name="travel_explore" className="text-sm" />
              Buscar película
            </Link>
            <Link to="/editor?nueva=1" className="font-headline text-xs font-bold uppercase tracking-wider px-4 py-2 rounded-lg bg-primary-glow/10 text-primary-glow hover:bg-primary-glow/20 flex items-center gap-1.5">
              <Icon name="movie_edit" className="text-sm" />
              Armar lección
            </Link>
          </>
        }
      />

      {overview.error && <ErrorBanner className="mb-6" error={overview.error} onRetry={overview.refetch} title="No se pudo cargar el resumen" />}
      {overview.loading && !data && <LoadingBlock label="Cargando resumen…" />}

      {data && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            <Stat label="Obras" value={fmtNumber(counts.works)} icon="movie" />
            <Stat
              label="Assets"
              value={fmtNumber(counts.assets)}
              icon="video_file"
              sub={`${fmtNumber(counts.assets_indexed)} indexados`}
            />
            <Stat
              label="Momentos"
              value={fmtNumber(counts.moments)}
              icon="movie_filter"
              sub={`${fmtNumber(counts.moments_labeled)} etiquetados`}
            />
            <div className="bg-surface-container rounded-xl p-4 border border-outline-variant/10">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">Lecciones</span>
                <Icon name="movie_edit" className="text-sm text-primary" />
              </div>
              <div className="font-headline text-2xl font-black">
                {fmtNumber(Object.values(lessonCounts).reduce((a, b) => a + (Number(b) || 0), 0))}
              </div>
              <div className="flex flex-wrap gap-1 mt-2">
                {Object.entries(lessonCounts)
                  .filter(([, n]) => n > 0)
                  .map(([status, n]) => (
                    <Pill key={status} tone={LESSON_STATUS[status]?.tone}>
                      {LESSON_STATUS[status]?.label ?? status}: {n}
                    </Pill>
                  ))}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-12 gap-6">
            <div className="col-span-12 xl:col-span-7 space-y-6">
              <Card>
                <CardHeader
                  title="Últimos trabajos"
                  icon="pending_actions"
                  actions={
                    <Link to="/trabajos" className="text-[10px] font-bold uppercase tracking-widest text-primary hover:underline">
                      Ver todos
                    </Link>
                  }
                />
                <div className="divide-y divide-outline-variant/10">
                  {jobs.length === 0 && (
                    <EmptyState icon="history" title="Sin trabajos todavía">
                      Registra una película en la Biblioteca y encola su indexado.
                    </EmptyState>
                  )}
                  {jobs.map((job) => (
                    <JobRow key={job.id} job={job} />
                  ))}
                </div>
              </Card>
            </div>

            <div className="col-span-12 xl:col-span-5 space-y-6">
              <AccountsCard webBaseUrl={settings.web_base_url} />

              <Card>
                <CardHeader
                  title="Almacenamiento"
                  icon="storage"
                  subtitle={storage.db_mb !== undefined ? `Base de datos: ${storage.db_mb} MB` : undefined}
                />
                <div className="p-4 space-y-4">
                  {storageLayers.length === 0 && <p className="text-xs text-on-surface-variant">Sin datos de almacenamiento.</p>}
                  {storageLayers.map(([name, layer]) => (
                    <StorageRow key={name} name={name} layer={layer} />
                  ))}
                </div>
              </Card>

              <Card>
                <CardHeader title="Credenciales" icon="key" subtitle="Solo se verifica que la variable exista; no se prueba la red." />
                <ul className="p-4 grid grid-cols-2 gap-2">
                  {(data.credentials ?? []).map((c) => (
                    <li key={c.name} className="flex items-center justify-between gap-2 bg-surface-low rounded-lg px-3 py-2">
                      <span className="text-xs font-bold truncate">{c.name}</span>
                      <Pill tone={CREDENTIAL_TONE[c.status] ?? 'warn'}>{c.status === 'OK' ? 'Lista' : c.status === 'MISSING' ? 'Falta' : c.status}</Pill>
                    </li>
                  ))}
                  {(data.credentials ?? []).length === 0 && <li className="text-xs text-on-surface-variant">Sin credenciales reportadas.</li>}
                </ul>
              </Card>

              <Card>
                <CardHeader title="Ajustes" icon="tune" subtitle="Se cambian en el .env de la raíz." />
                <div className="px-4 py-2">
                  <SettingRow label="Transcripción (ASR)" value={settings.asr_backend} />
                  <SettingRow label="Proveedor de IA" value={settings.llm_provider} />
                  <SettingRow label="Modelo Groq" value={settings.groq_model} />
                  <SettingRow label="Sitio público (puente TikTok)" value={settings.web_base_url} href={settings.web_base_url} />
                </div>
              </Card>
            </div>
          </div>
        </>
      )}
    </>
  );
}
