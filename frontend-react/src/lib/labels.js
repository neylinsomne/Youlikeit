/** Textos en español y tonos de color para estados del contrato. */

export const TONE_CLASSES = {
  neutral: 'bg-surface-highest text-on-surface-variant ring-outline-variant/40',
  info: 'bg-primary/15 text-primary ring-primary/30',
  ok: 'bg-tertiary/15 text-tertiary ring-tertiary/30',
  warn: 'bg-amber-400/15 text-amber-300 ring-amber-400/30',
  error: 'bg-error/15 text-error ring-error/30',
  primary: 'bg-primary-glow/15 text-primary-glow ring-primary-glow/30',
};

export const BAR_CLASSES = {
  neutral: 'bg-outline',
  info: 'bg-primary',
  ok: 'bg-tertiary',
  warn: 'bg-amber-300',
  error: 'bg-error',
  primary: 'bg-primary-glow',
};

export const LESSON_STATUS = {
  draft: { label: 'Borrador', tone: 'neutral', icon: 'edit_note' },
  rendering: { label: 'Renderizando', tone: 'info', icon: 'progress_activity' },
  rendered: { label: 'Por revisar', tone: 'warn', icon: 'rate_review' },
  approved: { label: 'Aprobada', tone: 'ok', icon: 'check_circle' },
  rejected: { label: 'Rechazada', tone: 'error', icon: 'block' },
  published: { label: 'Publicada', tone: 'primary', icon: 'public' },
};

export const JOB_STATUS = {
  queued: { label: 'En cola', tone: 'neutral', icon: 'schedule' },
  running: { label: 'En curso', tone: 'info', icon: 'progress_activity' },
  done: { label: 'Listo', tone: 'ok', icon: 'check' },
  error: { label: 'Error', tone: 'error', icon: 'error' },
};

export const JOB_TYPE = {
  index: { label: 'Indexar', icon: 'manage_search' },
  detect: { label: 'Detectar momentos', icon: 'movie_filter' },
  label: { label: 'Etiquetar', icon: 'label' },
  render: { label: 'Renderizar', icon: 'movie' },
  publish_tiktok: { label: 'Enviar a TikTok', icon: 'send' },
  publish_youtube: { label: 'Subir a YouTube', icon: 'cloud_upload' },
};

export const MOMENT_STATUS = {
  candidate: { label: 'Candidato', tone: 'neutral' },
  labeled: { label: 'Etiquetado', tone: 'info' },
  rejected: { label: 'Rechazado', tone: 'error' },
};

export const PUBLICATION_STATUS = {
  pending: { label: 'Pendiente', tone: 'neutral' },
  sent: { label: 'Enviado', tone: 'info' },
  published: { label: 'Publicado', tone: 'ok' },
  failed: { label: 'Falló', tone: 'error' },
};

export const PLATFORM = {
  tiktok: { label: 'TikTok', icon: 'music_video' },
  youtube: { label: 'YouTube', icon: 'smart_display' },
};

export const DIMENSIONS = [
  { id: 'emotion', label: 'Emoción', plural: 'Emociones' },
  { id: 'trope', label: 'Tropo', plural: 'Tropos' },
  { id: 'beat', label: 'Beat', plural: 'Beats' },
  { id: 'role', label: 'Rol', plural: 'Roles' },
  { id: 'theme', label: 'Tema', plural: 'Temas' },
];

export const DIMENSION_LABEL = Object.fromEntries(DIMENSIONS.map((d) => [d.id, d.label]));

export const DIMENSION_TONE = {
  emotion: 'bg-rose-400/15 text-rose-300 ring-rose-400/30',
  trope: 'bg-primary/15 text-primary ring-primary/30',
  beat: 'bg-violet-400/15 text-violet-300 ring-violet-400/30',
  role: 'bg-amber-400/15 text-amber-300 ring-amber-400/30',
  theme: 'bg-tertiary/15 text-tertiary ring-tertiary/30',
};

export const RIGHTS = {
  public_domain: { label: 'Dominio público', tone: 'ok', usable: true },
  open_license: { label: 'Licencia abierta', tone: 'ok', usable: true },
  owned: { label: 'Propio', tone: 'ok', usable: true },
  restricted: {
    label: 'Restringido',
    tone: 'error',
    usable: false,
    explain: 'La licencia restringe el uso (no comercial, sin derivados u otra condición): no se puede producir con este archivo.',
  },
  unknown: {
    label: 'Derechos desconocidos',
    tone: 'warn',
    usable: false,
    explain: 'No se pudo verificar que sea dominio público o licencia abierta. Busca otra copia con derechos claros.',
  },
};

export function rightsInfo(rights) {
  return RIGHTS[rights] ?? {
    label: rights || 'Sin dato',
    tone: 'warn',
    usable: false,
    explain: 'Estado de derechos no reconocido por el estudio.',
  };
}

export const PROVIDERS = {
  archive_org: 'Internet Archive',
  local: 'Biblioteca local',
};

export const INDEX_STEPS = [
  { id: 'probe', label: 'Sondeo', hint: 'Duración, resolución y fps' },
  { id: 'proxy', label: 'Proxy', hint: 'Copia liviana para cortes rápidos' },
  { id: 'analyze', label: 'Audio', hint: 'Envolvente de volumen y golpes' },
  { id: 'asr', label: 'Transcripción', hint: 'Texto con tiempos (ASR)' },
  { id: 'shots', label: 'Planos', hint: 'Cortes de cámara' },
];

export const STORAGE_LABELS = {
  raw_local: 'Biblioteca local (originales)',
  raw_remote_not_downloaded: 'Remotos (sin descargar)',
  segments: 'Segmentos en caché',
  analysis: 'Análisis',
  work: 'Trabajo temporal',
};

export const WHY_LABELS = {
  loudness: 'Volumen',
  sudden_onset: 'Golpe sonoro',
  shot_tempo: 'Ritmo de cortes',
  speech_intensity: 'Intensidad del habla',
  quote_anchor: 'Cita célebre',
  plot_anchor: 'Ancla de trama',
  climax_position: 'Cerca del clímax',
  trope_cues: 'Pistas del tropo',
};

export const ISSUE_TYPES = [
  { id: 'voice', label: 'Voz', icon: 'mic_off' },
  { id: 'caption', label: 'Subtítulo', icon: 'subtitles_off' },
  { id: 'timing', label: 'Tiempos', icon: 'timer_off' },
  { id: 'image', label: 'Imagen', icon: 'broken_image' },
  { id: 'rights', label: 'Derechos', icon: 'gavel' },
  { id: 'other', label: 'Otro', icon: 'warning' },
];

export const ISSUE_TYPE = Object.fromEntries(ISSUE_TYPES.map((t) => [t.id, t]));

export const CREDENTIAL_TONE = { OK: 'ok', MISSING: 'error' };

const MOODS = {
  fear: 'Tensión: drones graves y pulsos lentos',
  dread: 'Inquietante: pads oscuros, casi sin ritmo',
  shock: 'Golpes secos y silencios',
  tension: 'Ostinato tenso, cuerdas en staccato',
  anger: 'Percusión intensa',
  grief: 'Cuerdas lentas o piano solo',
  sadness: 'Piano íntimo',
  hope: 'Cuerdas ascendentes, luminoso',
  triumph: 'Orquestal épico',
  tenderness: 'Acústico cálido',
  awe: 'Ambiental amplio, coros suaves',
  disgust: 'Disonante, texturas raras',
  humor: 'Ligero y juguetón',
};

/** Mood orientativo para elegir la música en TikTok/YouTube (el estudio no mezcla música). */
export function suggestedMood(spec, script) {
  if (script?.mood) return script.mood;
  const [dimension, value] = String(spec ?? '').split(':');
  if (dimension === 'emotion' && MOODS[value]) return MOODS[value];
  return 'Neutro y reflexivo: piano o ambient a bajo volumen';
}

export function humanize(id) {
  return String(id ?? '').replaceAll('_', ' ');
}
