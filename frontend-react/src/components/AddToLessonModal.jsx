import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { useToast } from '../hooks/useToast';
import { fmtSeconds, msToClock } from '../lib/format';
import { LESSON_STATUS } from '../lib/labels';
import { EDIT_RESETS_STATUS, LOCKED_STATUS, toItemPatch } from '../lib/lesson';
import { Button, EmptyState, ErrorBanner, LoadingBlock, Modal, Notice, StatusPill } from './ui';

/**
 * Agrega un momento al final de una lección existente (GET lección completa + PATCH items).
 * Móntalo con key={moment?.id}; `onClose(updatedLesson?)`.
 */
export default function AddToLessonModal({ moment, onClose }) {
  const toast = useToast();
  const open = Boolean(moment);
  const lessons = useApi((signal) => api.lessons({}, { signal }), [], { enabled: open });
  const [lessonId, setLessonId] = useState(null);
  const [saving, setSaving] = useState(false);

  const items = lessons.data?.items ?? [];
  const selected = items.find((l) => l.id === lessonId);

  const add = async () => {
    if (!selected) return;
    setSaving(true);
    try {
      const full = await api.lesson(selected.id);
      const current = full.items ?? [];
      if (current.some((it) => it.moment_id === moment.id)) {
        toast.warn('Ese momento ya está en la lección.');
        return;
      }
      const next = [
        ...current.map(toItemPatch),
        { moment_id: moment.id, in_ms: moment.start_ms, out_ms: moment.end_ms, caption: '' },
      ];
      const updated = await api.patchLesson(full.id, { items: next });
      toast.success(`Momento agregado a «${updated.title}».`, 'Ajusta recortes y textos en el Editor.');
      onClose(updated);
    } catch (err) {
      toast.error(err, 'No se pudo agregar a la lección');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      open={open}
      title="Agregar a lección"
      onClose={() => onClose()}
      footer={
        <>
          <Button variant="ghost" onClick={() => onClose()}>
            Cancelar
          </Button>
          <Button variant="primary" icon="playlist_add" disabled={!selected} loading={saving} onClick={add}>
            Agregar
          </Button>
        </>
      }
    >
      {moment && (
        <p className="text-xs text-on-surface-variant mb-4">
          <span className="text-on-surface font-bold">{moment.work_title}</span> · {msToClock(moment.start_ms)} –{' '}
          {msToClock(moment.end_ms)} ({fmtSeconds(moment.end_ms - moment.start_ms)})
        </p>
      )}
      {lessons.error && <ErrorBanner error={lessons.error} onRetry={lessons.refetch} />}
      {lessons.loading && !lessons.data && <LoadingBlock label="Cargando lecciones…" />}
      {lessons.data && items.length === 0 && (
        <EmptyState icon="movie_edit" title="Todavía no hay lecciones">
          Crea una por tema en el <Link to="/editor?nueva=1" className="text-primary underline">Editor</Link>.
        </EmptyState>
      )}
      <div className="space-y-2">
        {items.map((l) => {
          const locked = LOCKED_STATUS.has(l.status);
          return (
            <label
              key={l.id}
              className={`flex items-center gap-3 rounded-lg border px-3 py-2 ${
                locked
                  ? 'border-outline-variant/10 opacity-50 cursor-not-allowed'
                  : lessonId === l.id
                    ? 'border-primary-glow/50 bg-primary-glow/5 cursor-pointer'
                    : 'border-outline-variant/15 hover:border-outline-variant/40 cursor-pointer'
              }`}
            >
              <input
                type="radio"
                name="lesson"
                className="accent-primary-glow"
                disabled={locked}
                checked={lessonId === l.id}
                onChange={() => setLessonId(l.id)}
              />
              <div className="flex-1 min-w-0">
                <div className="text-xs font-bold truncate">{l.title}</div>
                <div className="text-[10px] text-on-surface-variant font-mono">{l.spec}</div>
              </div>
              <StatusPill map={LESSON_STATUS} status={l.status} />
            </label>
          );
        })}
      </div>
      {selected && EDIT_RESETS_STATUS.has(selected.status) && (
        <Notice className="mt-3">Esta lección está «{LESSON_STATUS[selected.status]?.label}»: al agregar vuelve a borrador y habrá que renderizarla otra vez.</Notice>
      )}
    </Modal>
  );
}
