import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Card, EmptyState, ErrorBanner, Icon, LoadingBlock, PageHeader, Tabs } from '../components/ui';
import { useVocab } from '../hooks/useVocab';
import { DIMENSIONS, DIMENSION_TONE, humanize } from '../lib/labels';
import { inputCls } from '../lib/styles';

const NO_ITEMS = [];

function normalize(text) {
  return String(text ?? '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '');
}

function matches(entry, q) {
  if (!q) return true;
  return [entry.id, entry.es, entry.en, entry.desc_es, entry.desc_en].some((f) => normalize(f).includes(q));
}

export default function Vocabulario() {
  const vocab = useVocab();
  const [dimension, setDimension] = useState('emotion');
  const [query, setQuery] = useState('');
  const q = normalize(query.trim());

  const entries = (vocab.vocab?.[dimension] ?? NO_ITEMS).filter((e) => matches(e, q));
  const tabs = DIMENSIONS.map((d) => ({
    id: d.id,
    label: d.plural,
    count: vocab.vocab ? (vocab.vocab[d.id] ?? NO_ITEMS).filter((e) => matches(e, q)).length : undefined,
  }));

  return (
    <>
      <PageHeader
        title="Vocabulario"
        subtitle="Las etiquetas válidas para clasificar momentos. Son de solo lectura: viven en data/vocab/ con el código."
      />

      <div className="flex flex-wrap items-center gap-3 mb-6">
        <Tabs value={dimension} onChange={setDimension} tabs={tabs} />
        <div className="relative flex-1 min-w-60 max-w-md">
          <Icon name="search" className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-sm" />
          <input
            className={`${inputCls} pl-9`}
            placeholder="Buscar en español o inglés…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Buscar en el vocabulario"
          />
        </div>
      </div>

      {vocab.error && <ErrorBanner className="mb-4" error={vocab.error} onRetry={vocab.refetch} title="No se pudo cargar el vocabulario" />}
      {vocab.loading && !vocab.vocab && <LoadingBlock label="Cargando vocabulario…" />}
      {vocab.vocab && entries.length === 0 && <EmptyState icon="search_off" title="Nada coincide con la búsqueda" />}

      <div className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-4">
        {entries.map((e) => {
          const spec = `${dimension}:${e.id}`;
          return (
            <Card key={e.id} className="p-4 flex flex-col gap-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="text-sm font-bold">{e.es || humanize(e.id)}</h3>
                  {e.en && e.en !== e.es && <p className="text-[11px] text-on-surface-variant">{e.en}</p>}
                </div>
                <code className={`text-[10px] px-1.5 py-0.5 rounded ring-1 whitespace-nowrap ${DIMENSION_TONE[dimension]}`}>{e.id}</code>
              </div>
              {e.desc_es && <p className="text-xs text-on-surface-variant">{e.desc_es}</p>}
              {!e.desc_es && e.desc_en && <p className="text-xs text-on-surface-variant italic">{e.desc_en}</p>}
              {Array.isArray(e.themes) && e.themes.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {e.themes.map((t) => (
                    <span key={t} className="text-[10px] bg-surface-highest text-on-surface-variant px-1.5 py-0.5 rounded">
                      {humanize(t)}
                    </span>
                  ))}
                </div>
              )}
              <div className="mt-auto pt-2 flex gap-3 text-[10px] font-bold uppercase tracking-widest">
                <Link to={`/momentos?dimension=${dimension}&value=${encodeURIComponent(e.id)}`} className="text-primary hover:underline">
                  Ver momentos
                </Link>
                <Link to={`/momentos?tab=buscar&spec=${encodeURIComponent(spec)}`} className="text-primary hover:underline">
                  Entre obras
                </Link>
                <Link to={`/editor?nueva=1&spec=${encodeURIComponent(spec)}`} className="text-primary-glow hover:underline">
                  Armar lección
                </Link>
              </div>
            </Card>
          );
        })}
      </div>
    </>
  );
}
