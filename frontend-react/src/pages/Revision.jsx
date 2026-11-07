import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { YOUTUBE_CONNECT_URL, api, versionedUrl } from '../api/client';
import ClockInput from '../components/ClockInput';
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
import { useJobTracker } from '../hooks/useJobsSocket';
import { useToast } from '../hooks/useToast';
import { fmtDate, localInputToIsoUtc, secToClock } from '../lib/format';
import { isTerminal, jobPct } from '../lib/jobs';
import { ISSUE_TYPE, ISSUE_TYPES, LESSON_STATUS, PLATFORM, PUBLICATION_STATUS, suggestedMood } from '../lib/labels';
import { inputCls, selectCls, textareaCls } from '../lib/styles';

const NO_ITEMS = [];
const REVIEW_TABS = ['rendered', 'approved', 'rejected', 'published'];
const round1 = (x) => Math.round(x * 10) / 10;

// ───────────────────────────── Issues ─────────────────────────────

function IssueBar({ issues, duration, onSeek }) {
  if (!duration) return null;
  return (
    <div className="relative h-2 bg-surface-highest rounded-full" aria-label="Issues sobre la línea de tiempo">
      {issues.map((iss) => {
        const left = Math.max(0, Math.min(100, (iss.start_s / duration) * 100));
        const width = Math.max(0.8, Math.min(100 - left, ((iss.end_s - iss.start_s) / duration) * 100));
        return (
          <button
            key={iss.id}
            type="button"
            title={`${ISSUE_TYPE[iss.issue_type]?.label ?? iss.issue_type}: ${secToClock(iss.start_s)} – ${secToClock(iss.end_s)}`}
            onClick={() => onSeek(iss.start_s)}
            className="absolute top-0 h-2 rounded-full bg-error/80 hover:bg-error cursor-pointer"
            style={{ left: `${left}%`, width: `${width}%` }}
          />
        );
      })}
    </div>
  );
}

function IssueForm({ videoRef, lessonId, onAdded }) {
  const toast = useToast();
  const [form, setForm] = useState({ issue_type: 'caption', start_s: 0, end_s: 0, note: '' });
  const [busy, setBusy] = useState(false);
  const set = (patch) => setForm((f) => ({ ...f, ...patch }));
  const valid = form.end_s > form.start_s;

  const stamp = (field) => {
    const t = videoRef.current?.currentTime;
    if (t === undefined || t === null) return;
    set({ [field]: round1(t) });
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!valid) return;
    setBusy(true);
    try {
      const issue = await api.addIssue(lessonId, {
        issue_type: form.issue_type,
        start_s: form.start_s,
        end_s: form.end_s,
        note: form.note.trim(),
      });
      onAdded(issue);
      toast.success('Issue registrado');
      setForm((f) => ({ ...f, note: '', start_s: f.end_s, end_s: f.end_s }));
    } catch (err) {
      toast.error(err, 'No se pudo registrar el issue');
    } finally {
      setBusy(false);
    }
  };

  const timeField = (field, label) => (
    <div>
      <span className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant block mb-1">{label}</span>
      <div className="flex items-center gap-1">
        <ClockInput key={form[field]} valueMs={form[field] * 1000} aria-label={label} onCommit={(ms) => set({ [field]: round1(ms / 1000) })} />
        <Button size="xs" variant="ghost" icon="my_location" title="Marcar tiempo actual del video" onClick={() => stamp(field)}>
          Ahora
        </Button>
      </div>
    </div>
  );

  return (
    <form onSubmit={submit} className="bg-surface-low rounded-lg p-3 space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {ISSUE_TYPES.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => set({ issue_type: t.id })}
            className={`text-[10px] font-bold px-2.5 py-1 rounded-full uppercase cursor-pointer flex items-center gap-1 ${
              form.issue_type === t.id ? 'bg-error/20 text-error' : 'bg-surface-container text-on-surface-variant hover:text-on-surface'
            }`}
          >
            <Icon name={t.icon} className="text-[12px]" />
            {t.label}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap items-end gap-4">
        {timeField('start_s', 'Desde')}
        {timeField('end_s', 'Hasta')}
      </div>
      {!valid && (form.start_s > 0 || form.end_s > 0) && <p className="text-[10px] text-error">«Hasta» debe ir después de «Desde».</p>}
      <input className={inputCls} value={form.note} placeholder="Qué pasa (p. ej. el subtítulo tapa la cara)" onChange={(e) => set({ note: e.target.value })} aria-label="Nota del issue" />
      <div className="flex justify-end">
        <Button type="submit" size="sm" variant="danger" icon="flag" disabled={!valid} loading={busy}>
          Registrar issue
        </Button>
      </div>
    </form>
  );
}

function IssuesCard({ lessonId, videoRef, duration, onSeek, onCountChange }) {
  const toast = useToast();
  const issues = useApi((signal) => api.issues(lessonId, { signal }), [lessonId]);
  const [deleting, setDeleting] = useState(null);
  const list = [...(issues.data?.items ?? NO_ITEMS)].sort((a, b) => a.start_s - b.start_s);

  const remove = async (issue) => {
    setDeleting(issue.id);
    try {
      await api.deleteIssue(lessonId, issue.id);
      issues.setData((prev) => ({ ...prev, items: (prev?.items ?? []).filter((i) => i.id !== issue.id) }));
      onCountChange(list.length - 1);
    } catch (err) {
      toast.error(err, 'No se pudo borrar el issue');
    } finally {
      setDeleting(null);
    }
  };

  return (
    <Card>
      <CardHeader title={`Issues (${list.length})`} icon="flag" subtitle="Clic en un issue para saltar a ese momento del video." />
      <div className="p-4 space-y-3">
        <IssueBar issues={list} duration={duration} onSeek={onSeek} />
        {issues.error && <ErrorBanner error={issues.error} onRetry={issues.refetch} />}
        {issues.loading && !issues.data && <LoadingBlock />}
        <div className="space-y-2">
          {list.map((iss) => {
            const t = ISSUE_TYPE[iss.issue_type] ?? { label: iss.issue_type, icon: 'warning' };
            return (
              <div key={iss.id} className="flex items-center gap-2 bg-error-container/15 border border-error/20 rounded-lg px-3 py-2">
                <button type="button" onClick={() => onSeek(iss.start_s)} className="flex-1 min-w-0 flex items-center gap-2 text-left cursor-pointer group">
                  <Icon name={t.icon} className="text-error text-sm" />
                  <span className="text-[10px] font-bold text-error uppercase">{t.label}</span>
                  <span className="text-[10px] font-mono text-on-surface-variant group-hover:text-primary">
                    {secToClock(iss.start_s)} – {secToClock(iss.end_s)}
                  </span>
                  {iss.note && <span className="text-[11px] text-on-surface truncate">· {iss.note}</span>}
                </button>
                <button
                  type="button"
                  aria-label="Borrar issue"
                  disabled={deleting === iss.id}
                  onClick={() => remove(iss)}
                  className="text-on-surface-variant hover:text-error cursor-pointer disabled:opacity-40"
                >
                  <Icon name={deleting === iss.id ? 'progress_activity' : 'delete'} className={`text-sm ${deleting === iss.id ? 'animate-spin' : ''}`} />
                </button>
              </div>
            );
          })}
          {issues.data && list.length === 0 && <p className="text-[11px] text-on-surface-variant text-center py-1">Sin issues registrados.</p>}
        </div>
        <IssueForm
          videoRef={videoRef}
          lessonId={lessonId}
          onAdded={(issue) => {
            issues.setData((prev) => ({ ...prev, items: [...(prev?.items ?? []), issue] }));
            onCountChange(list.length + 1);
          }}
        />
      </div>
    </Card>
  );
}

// ───────────────────────────── Publicar ─────────────────────────────

function JobProgress({ job }) {
  if (!job) return null;
  const pct = jobPct(job);
  const tone = job.status === 'error' ? 'error' : job.status === 'done' ? 'ok' : 'info';
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px] text-on-surface-variant">
        <span>
          Trabajo #{job.id} · <StatusLabel status={job.status} />
          {job.progress?.stage ? ` · ${job.progress.stage}` : ''}
        </span>
        <span className="font-mono">{pct === null ? '…' : `${Math.round(pct)}%`}</span>
      </div>
      <ProgressBar value={pct ?? 0} indeterminate={pct === null && !isTerminal(job.status)} tone={tone} />
      {job.progress?.detail && <p className="text-[10px] text-on-surface-variant">{job.progress.detail}</p>}
      {job.status === 'error' && job.error && <p className="text-[11px] text-error break-words">{job.error}</p>}
    </div>
  );
}

function StatusLabel({ status }) {
  const labels = { queued: 'en cola', running: 'en curso', done: 'listo', error: 'error' };
  return <>{labels[status] ?? status}</>;
}

function TikTokCard({ lesson, tracker }) {
  const toast = useToast();
  const accounts = useApi((signal) => api.tiktokAccounts({ signal }), []);
  const [openId, setOpenId] = useState('');
  const [busy, setBusy] = useState(false);
  const list = accounts.data?.accounts ?? NO_ITEMS;
  const chosen = openId || list[0]?.open_id || '';
  const active = tracker.job && !isTerminal(tracker.job.status);
  const bridgeDown = accounts.error?.status === 502 || accounts.error?.status === 503;

  const send = async () => {
    const account = list.find((a) => a.open_id === chosen);
    if (!window.confirm(`¿Enviar «${lesson.title}» como borrador a la cuenta de TikTok «${account?.display_name ?? chosen}»?`)) return;
    setBusy(true);
    try {
      const job = await api.publishTikTok(lesson.id, chosen);
      tracker.track(job);
      toast.info(`Envío a TikTok en cola (#${job.id})`);
    } catch (err) {
      toast.error(err, 'No se pudo enviar a TikTok');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader title="TikTok" icon="music_video" subtitle="Llega como borrador a la bandeja de TikTok: ahí eliges la música y publicas." />
      <div className="p-4 space-y-3">
        {accounts.error &&
          (bridgeDown && !accounts.error.offline ? (
            <Notice tone="error" icon="cloud_off">
              <b>Puente web no disponible.</b> El sitio público no respondió; revisa WEB_BASE_URL y STUDIO_API_KEY.
              <span className="block opacity-80 mt-0.5">{accounts.error.detail}</span>
              <button type="button" onClick={accounts.refetch} className="mt-1 underline cursor-pointer">
                Reintentar
              </button>
            </Notice>
          ) : (
            <ErrorBanner error={accounts.error} onRetry={accounts.refetch} title="No se pudieron leer las cuentas" />
          ))}
        {accounts.loading && !accounts.data && <LoadingBlock label="Consultando cuentas conectadas…" className="py-4" />}
        {accounts.data && list.length === 0 && (
          <Notice tone="warn">No hay cuentas de TikTok conectadas. Inicia sesión con TikTok en el sitio público para autorizar el envío de borradores.</Notice>
        )}
        {list.length > 0 && (
          <Field label="Cuenta">
            {(id) => (
              <select id={id} className={selectCls} value={chosen} onChange={(e) => setOpenId(e.target.value)}>
                {list.map((a) => (
                  <option key={a.open_id} value={a.open_id}>
                    {a.display_name || a.open_id}
                  </option>
                ))}
              </select>
            )}
          </Field>
        )}
        <Button variant="primary" icon="send" className="w-full" disabled={!chosen || active} loading={busy} onClick={send}>
          Enviar a TikTok como borrador
        </Button>
        <JobProgress job={tracker.job} />
      </div>
    </Card>
  );
}

function YouTubeCard({ lesson, tracker }) {
  const toast = useToast();
  const status = useApi((signal) => api.youtubeStatus({ signal }), []);
  const [privacy, setPrivacy] = useState('private');
  const [publishAt, setPublishAt] = useState('');
  const [busy, setBusy] = useState(false);
  const active = tracker.job && !isTerminal(tracker.job.status);
  const connected = status.data?.connected === true;
  const { refetch } = status;

  // Al volver del OAuth de Google (otra pestaña) refrescamos el estado.
  useEffect(() => {
    window.addEventListener('focus', refetch);
    return () => window.removeEventListener('focus', refetch);
  }, [refetch]);

  const upload = async () => {
    const body = { privacy: publishAt ? 'private' : privacy };
    if (publishAt) {
      const iso = localInputToIsoUtc(publishAt);
      if (!iso || new Date(iso).getTime() <= Date.now()) {
        toast.warn('La fecha programada debe estar en el futuro.');
        return;
      }
      body.publish_at = iso;
    }
    setBusy(true);
    try {
      const job = await api.publishYouTube(lesson.id, body);
      tracker.track(job);
      toast.info(`Subida a YouTube en cola (#${job.id})`);
    } catch (err) {
      toast.error(err, 'No se pudo subir a YouTube');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title="YouTube"
        icon="smart_display"
        subtitle={connected ? `Canal: ${status.data.channel_title ?? 'conectado'}` : 'Se sube privado; opcionalmente con fecha de publicación.'}
      />
      <div className="p-4 space-y-3">
        {status.error && <ErrorBanner error={status.error} onRetry={refetch} title="No se pudo leer el estado de YouTube" />}
        {status.loading && !status.data && <LoadingBlock className="py-4" />}
        {connected && status.data.warning && <Notice tone="warn">{status.data.warning}</Notice>}
        {status.data && !connected && (
          <div className="space-y-2">
            <Notice tone="warn">YouTube no está conectado en este estudio.</Notice>
            <div className="flex gap-2">
              <a
                href={YOUTUBE_CONNECT_URL}
                target="_blank"
                rel="noreferrer"
                className="font-headline flex-1 text-xs font-bold uppercase tracking-wider px-4 py-2 rounded-lg bg-primary-glow/10 text-primary-glow hover:bg-primary-glow/20 flex items-center justify-center gap-1.5"
              >
                <Icon name="link" className="text-sm" />
                Conectar YouTube
              </a>
              <Button variant="ghost" icon="refresh" loading={status.loading} onClick={refetch}>
                Ya conecté
              </Button>
            </div>
          </div>
        )}
        {connected && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Privacidad" hint={publishAt ? 'Con fecha, queda privado hasta esa hora.' : undefined}>
                {(id) => (
                  <select id={id} className={selectCls} value={publishAt ? 'private' : privacy} disabled={Boolean(publishAt)} onChange={(e) => setPrivacy(e.target.value)}>
                    <option value="private">Privado</option>
                    <option value="unlisted">No listado</option>
                    <option value="public">Público</option>
                  </select>
                )}
              </Field>
              <Field label="Publicar el (opcional)" hint="Hora local de esta PC.">
                {(id) => <input id={id} type="datetime-local" className={inputCls} value={publishAt} onChange={(e) => setPublishAt(e.target.value)} />}
              </Field>
            </div>
            <Button variant="primary" icon="cloud_upload" className="w-full" disabled={active} loading={busy} onClick={upload}>
              Subir a YouTube
            </Button>
          </>
        )}
        <JobProgress job={tracker.job} />
      </div>
    </Card>
  );
}

function PublicationsCard({ lessonId, refreshKey }) {
  const pubs = useApi((signal) => api.publications(lessonId, { signal }), [lessonId, refreshKey]);
  const list = pubs.data?.items ?? NO_ITEMS;
  return (
    <Card>
      <CardHeader title="Historial de publicación" icon="history" />
      <div className="p-4 space-y-2">
        {pubs.error && <ErrorBanner error={pubs.error} onRetry={pubs.refetch} />}
        {pubs.loading && !pubs.data && <LoadingBlock className="py-4" />}
        {pubs.data && list.length === 0 && <p className="text-[11px] text-on-surface-variant">Todavía no se ha enviado a ninguna plataforma.</p>}
        {list.map((p) => (
          <div key={p.id} className="flex items-start gap-3 bg-surface-low rounded-lg px-3 py-2">
            <Icon name={PLATFORM[p.platform]?.icon ?? 'public'} className="text-primary text-base mt-0.5" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-xs font-bold">{PLATFORM[p.platform]?.label ?? p.platform}</span>
                <StatusPill map={PUBLICATION_STATUS} status={p.status} />
                <span className="text-[10px] text-on-surface-variant">{fmtDate(p.created_at)}</span>
              </div>
              {p.external_id && <p className="text-[10px] font-mono text-on-surface-variant truncate">{p.external_id}</p>}
              {p.detail && <p className="text-[11px] text-on-surface-variant break-words">{p.detail}</p>}
            </div>
            {p.url && (
              <a href={p.url} target="_blank" rel="noreferrer" className="text-primary hover:text-primary-glow" aria-label="Abrir publicación">
                <Icon name="open_in_new" className="text-sm" />
              </a>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

// ───────────────────────────── Panel de revisión ─────────────────────────────

function ReviewPanel({ lesson, onLessonUpdated, onIssuesCount, refetchLesson }) {
  const toast = useToast();
  const videoRef = useRef(null);
  const [duration, setDuration] = useState(lesson.duration_s ?? 0);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(null);
  const [pubKey, setPubKey] = useState(0);

  const onPublishFinish = (ev) => {
    if (ev.status === 'done') toast.success(ev.type === 'publish_youtube' ? 'Subido a YouTube' : 'Enviado a TikTok como borrador');
    else toast.error({ detail: ev.detail || 'La publicación falló' }, ev.type === 'publish_youtube' ? 'YouTube' : 'TikTok');
    setPubKey((k) => k + 1);
    refetchLesson();
  };
  const tiktokTracker = useJobTracker({ onFinish: onPublishFinish });
  const youtubeTracker = useJobTracker({ onFinish: onPublishFinish });

  const seek = (s) => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = s;
    v.play().catch((err) => console.warn('[estudio] el navegador no pudo reproducir', err));
  };

  const act = async (what, fn, okMessage) => {
    setBusy(what);
    try {
      const updated = await fn();
      toast.success(okMessage);
      onLessonUpdated(updated);
    } catch (err) {
      toast.error(err, what === 'approve' ? 'No se pudo aprobar' : 'No se pudo rechazar');
    } finally {
      setBusy(null);
    }
  };

  const canApprove = lesson.status === 'rendered';
  const canReject = lesson.status === 'rendered' || lesson.status === 'approved';
  const items = lesson.items ?? NO_ITEMS;
  const durations = items.map((it) => Math.max(0, (it.out_ms - it.in_ms) / 1000));
  const offsets = durations.map((_, i) => durations.slice(0, i).reduce((a, b) => a + b, 0));

  return (
    <div className="grid grid-cols-12 gap-6">
      <div className="col-span-12 2xl:col-span-7 space-y-6">
        <Card>
          <div className="p-4 flex flex-col items-center gap-3">
            {lesson.video_url ? (
              <video
                ref={videoRef}
                key={lesson.updated_at}
                src={versionedUrl(lesson.video_url, lesson.updated_at)}
                controls
                playsInline
                preload="metadata"
                onLoadedMetadata={(e) => setDuration(e.currentTarget.duration || lesson.duration_s || 0)}
                className="aspect-[9/16] max-h-[620px] bg-black rounded-lg"
              />
            ) : (
              <EmptyState icon="videocam_off" title="Sin video renderizado">
                Renderiza la lección en el <Link className="text-primary underline" to={`/editor?id=${lesson.id}`}>Editor</Link>.
              </EmptyState>
            )}
            <div className="w-full flex flex-wrap items-center justify-between gap-2 text-[10px] text-on-surface-variant">
              <span>
                {lesson.duration_s ? `${Number(lesson.duration_s).toFixed(1)} s` : '—'} · {items.length} segmentos · actualizado {fmtDate(lesson.updated_at)}
              </span>
              <Link to={`/editor?id=${lesson.id}`} className="text-primary font-bold uppercase tracking-widest hover:underline flex items-center gap-1">
                <Icon name="movie_edit" className="text-sm" />
                Abrir en el editor
              </Link>
            </div>
          </div>
        </Card>

        <IssuesCard lessonId={lesson.id} videoRef={videoRef} duration={duration} onSeek={seek} onCountChange={onIssuesCount} />

        <Card>
          <CardHeader title="Guion y textos" icon="subtitles" subtitle="Tiempos aproximados (≈) sumando los recortes." />
          <div className="p-4 space-y-3">
            {lesson.script?.hook && (
              <p className="text-xs">
                <span className="bg-primary/20 text-primary text-[9px] font-bold px-2 py-0.5 rounded mr-2">GANCHO</span>
                <span className="italic">{lesson.script.hook}</span>
              </p>
            )}
            <ol className="space-y-2">
              {items.map((it, i) => {
                const seg = lesson.script?.segments?.find((s) => s.idx === i);
                return (
                  <li key={`${it.moment_id}-${i}`} className="flex gap-3 text-xs">
                    <button type="button" onClick={() => seek(offsets[i])} className="font-mono text-[10px] text-primary hover:underline cursor-pointer w-14 text-left flex-shrink-0">
                      ≈{secToClock(offsets[i])}
                    </button>
                    <div className="min-w-0">
                      <p className="font-bold">
                        {it.work_title} <span className="font-normal text-on-surface-variant">({it.work_year ?? 's. f.'})</span>
                      </p>
                      {it.caption && <p className="text-tertiary">«{it.caption}»</p>}
                      {seg?.narration && <p className="text-on-surface-variant italic">Voz: {seg.narration}</p>}
                    </div>
                  </li>
                );
              })}
            </ol>
            {lesson.script?.outro && (
              <p className="text-xs">
                <span className="bg-tertiary/20 text-tertiary text-[9px] font-bold px-2 py-0.5 rounded mr-2">CIERRE</span>
                <span className="italic">{lesson.script.outro}</span>
              </p>
            )}
          </div>
        </Card>
      </div>

      <div className="col-span-12 2xl:col-span-5 space-y-6">
        <Card>
          <CardHeader title="Decisión" icon="gavel" actions={<StatusPill map={LESSON_STATUS} status={lesson.status} />} />
          <div className="p-4 space-y-3">
            {lesson.status === 'rejected' && lesson.reject_reason && (
              <Notice tone="error" icon="block">
                Motivo del rechazo: {lesson.reject_reason}
              </Notice>
            )}
            {lesson.status === 'draft' && <Notice tone="info">Esta lección está en borrador: renderízala para poder revisarla.</Notice>}
            <Button
              variant="ok"
              size="lg"
              icon="check_circle"
              className="w-full"
              disabled={!canApprove || busy !== null}
              loading={busy === 'approve'}
              title={canApprove ? undefined : 'Solo se aprueban lecciones renderizadas («Por revisar»)'}
              onClick={() => act('approve', () => api.approveLesson(lesson.id), 'Lección aprobada')}
            >
              Aprobar
            </Button>
            {canReject && (
              <>
                <Field label="Motivo del rechazo">
                  {(id) => (
                    <textarea id={id} rows={2} className={textareaCls} value={reason} placeholder="Qué hay que corregir…" onChange={(e) => setReason(e.target.value)} />
                  )}
                </Field>
                <Button
                  variant="danger"
                  icon="cancel"
                  className="w-full"
                  disabled={!reason.trim() || busy !== null}
                  loading={busy === 'reject'}
                  onClick={() => act('reject', () => api.rejectLesson(lesson.id, reason.trim()), 'Lección rechazada')}
                >
                  Rechazar
                </Button>
              </>
            )}
          </div>
        </Card>

        {lesson.status === 'approved' && (
          <>
            <TikTokCard lesson={lesson} tracker={tiktokTracker} />
            <YouTubeCard lesson={lesson} tracker={youtubeTracker} />
          </>
        )}
        {(lesson.status === 'approved' || lesson.status === 'published') && <PublicationsCard lessonId={lesson.id} refreshKey={pubKey} />}

        <Card className="p-4">
          <p className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-1 flex items-center gap-1">
            <Icon name="music_note" className="text-sm text-tertiary" />
            Música
          </p>
          <p className="text-xs">
            La música se elige en TikTok/YouTube. Mood sugerido: <b className="text-tertiary">{suggestedMood(lesson.spec, lesson.script)}</b>
          </p>
        </Card>
      </div>
    </div>
  );
}

// ───────────────────────────── Página ─────────────────────────────

export default function Revision() {
  const [sp, setSp] = useSearchParams();
  const tab = REVIEW_TABS.includes(sp.get('estado')) ? sp.get('estado') : 'rendered';
  const lessons = useApi((signal) => api.lessons({}, { signal }), []);
  const all = lessons.data?.items ?? NO_ITEMS;
  const list = all.filter((l) => l.status === tab);
  const selectedId = Number(sp.get('id')) || list[0]?.id || null;
  const lesson = useApi((signal) => api.lesson(selectedId, { signal }), [selectedId], { enabled: Boolean(selectedId) });
  const current = lesson.data?.id === selectedId ? lesson.data : null;

  const select = (id, estado = tab) => setSp({ estado, id: String(id) }, { replace: true });

  const onLessonUpdated = (updated) => {
    lesson.setData(updated);
    lessons.setData((prev) => (prev ? { ...prev, items: prev.items.map((l) => (l.id === updated.id ? { ...l, ...updated } : l)) } : prev));
    if (REVIEW_TABS.includes(updated.status)) select(updated.id, updated.status);
  };

  const onIssuesCount = (n) => {
    lessons.setData((prev) => (prev ? { ...prev, items: prev.items.map((l) => (l.id === selectedId ? { ...l, issues: n } : l)) } : prev));
  };

  const refetchLesson = () => {
    lesson.refetch();
    lessons.refetch();
  };

  return (
    <>
      <PageHeader
        title="Revisión"
        subtitle="Mira cada lección en 9:16, marca problemas con su tiempo, aprueba o rechaza y publica: TikTok como borrador y YouTube privado/programado."
        actions={
          <Tabs
            value={tab}
            onChange={(estado) => setSp({ estado }, { replace: true })}
            tabs={REVIEW_TABS.map((s) => ({ id: s, label: LESSON_STATUS[s].label, count: all.filter((l) => l.status === s).length }))}
          />
        }
      />

      {lessons.error && <ErrorBanner className="mb-4" error={lessons.error} onRetry={lessons.refetch} title="No se pudieron cargar las lecciones" />}

      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-12 lg:col-span-3 space-y-3">
          {lessons.loading && !lessons.data && <LoadingBlock />}
          {lessons.data && list.length === 0 && (
            <EmptyState icon="inbox" title={`Nada en «${LESSON_STATUS[tab].label}»`}>
              {tab === 'rendered' ? 'Renderiza una lección en el Editor para revisarla aquí.' : 'Sin lecciones en este estado.'}
            </EmptyState>
          )}
          {list.map((l) => (
            <button
              key={l.id}
              type="button"
              onClick={() => select(l.id)}
              className={`w-full text-left bg-surface-container rounded-xl p-4 border cursor-pointer transition-all ${
                l.id === selectedId ? 'border-primary-glow/50 ring-1 ring-primary-glow/20' : 'border-outline-variant/10 hover:border-outline-variant/30'
              }`}
            >
              <div className="flex items-start gap-3">
                <div className="w-10 h-14 bg-surface-highest rounded-md flex-shrink-0 flex items-center justify-center">
                  <Icon name="smart_display" className="text-xl text-outline" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-bold truncate">{l.title}</div>
                  <div className="text-[10px] text-on-surface-variant mt-0.5">
                    {l.duration_s ? `${Number(l.duration_s).toFixed(1)} s` : '—'} · {l.spec}
                  </div>
                  <div className="flex items-center gap-2 mt-2 flex-wrap">
                    <StatusPill map={LESSON_STATUS} status={l.status} />
                    {l.issues > 0 && (
                      <Pill tone="warn" icon="flag">
                        {l.issues}
                      </Pill>
                    )}
                  </div>
                </div>
              </div>
            </button>
          ))}
        </div>

        <div className="col-span-12 lg:col-span-9">
          {lesson.error && <ErrorBanner error={lesson.error} onRetry={lesson.refetch} title="No se pudo abrir la lección" />}
          {selectedId && !current && lesson.loading && <LoadingBlock label="Abriendo lección…" />}
          {!selectedId && lessons.data && (
            <EmptyState icon="rate_review" title="Elige una lección de la lista" />
          )}
          {current && (
            <ReviewPanel key={current.id} lesson={current} onLessonUpdated={onLessonUpdated} onIssuesCount={onIssuesCount} refetchLesson={refetchLesson} />
          )}
        </div>
      </div>
    </>
  );
}
