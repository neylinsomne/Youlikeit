import { useEffect, useId } from 'react';
import { describeError } from '../lib/errors';
import { BAR_CLASSES, TONE_CLASSES } from '../lib/labels';
import { labelCls } from '../lib/styles';

export function Icon({ name, className = '', fill = false, title }) {
  return (
    <span
      aria-hidden={title ? undefined : true}
      title={title}
      className={`material-symbols-outlined select-none ${className}`}
      style={fill ? { fontVariationSettings: "'FILL' 1" } : undefined}
    >
      {name}
    </span>
  );
}

export function Spinner({ className = 'text-sm' }) {
  return <Icon name="progress_activity" className={`animate-spin ${className}`} />;
}

export function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 mb-6">
      <div>
        <h2 className="font-headline text-3xl font-black tracking-tighter uppercase mb-1">{title}</h2>
        {subtitle && <p className="text-sm text-on-surface-variant max-w-3xl">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Card({ className = '', children, ...rest }) {
  return (
    <section className={`bg-surface-container rounded-xl border border-outline-variant/10 ${className}`} {...rest}>
      {children}
    </section>
  );
}

export function CardHeader({ title, icon, subtitle, actions }) {
  return (
    <div className="px-4 py-3 border-b border-outline-variant/10 flex flex-wrap items-center justify-between gap-2">
      <div className="min-w-0">
        <h3 className="font-headline text-xs font-bold tracking-widest uppercase flex items-center gap-2">
          {icon && <Icon name={icon} className="text-sm text-primary" />}
          {title}
        </h3>
        {subtitle && <p className="text-[11px] text-on-surface-variant mt-0.5">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

const BUTTON_VARIANTS = {
  primary: 'bg-linear-to-br from-primary to-primary-glow text-on-primary hover:brightness-110',
  subtle: 'bg-surface-highest text-on-surface hover:bg-surface-bright',
  ghost: 'text-on-surface-variant hover:text-on-surface hover:bg-surface-high',
  accent: 'bg-primary-glow/10 text-primary-glow hover:bg-primary-glow/20',
  ok: 'bg-tertiary/15 text-tertiary border border-tertiary/30 hover:bg-tertiary/25',
  danger: 'bg-error-container/30 text-error border border-error/30 hover:bg-error-container/50',
};

const BUTTON_SIZES = {
  xs: 'text-[10px] px-2 py-1',
  sm: 'text-[10px] px-2.5 py-1.5',
  md: 'text-xs px-4 py-2',
  lg: 'text-xs px-5 py-3',
};

export function Button({
  variant = 'subtle',
  size = 'md',
  icon,
  loading = false,
  disabled = false,
  type = 'button',
  className = '',
  children,
  ...rest
}) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      className={`font-headline inline-flex items-center justify-center gap-1.5 rounded-lg font-bold uppercase tracking-wider transition-colors cursor-pointer active:scale-[0.98] disabled:opacity-40 disabled:cursor-not-allowed disabled:active:scale-100 ${BUTTON_VARIANTS[variant]} ${BUTTON_SIZES[size]} ${className}`}
      {...rest}
    >
      {loading ? <Spinner /> : icon ? <Icon name={icon} className="text-sm" /> : null}
      {children}
    </button>
  );
}

export function Pill({ tone = 'neutral', icon, className = '', title, children }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full ring-1 whitespace-nowrap ${TONE_CLASSES[tone] ?? TONE_CLASSES.neutral} ${className}`}
    >
      {icon && <Icon name={icon} className="text-[12px]" />}
      {children}
    </span>
  );
}

/** Pastilla para un estado usando un mapa {estado: {label, tone, icon}} de lib/labels. */
export function StatusPill({ map, status }) {
  const info = map?.[status];
  return (
    <Pill tone={info?.tone ?? 'neutral'} icon={info?.icon === 'progress_activity' ? undefined : info?.icon}>
      {info?.icon === 'progress_activity' && <Spinner className="text-[12px]" />}
      {info?.label ?? status ?? '—'}
    </Pill>
  );
}

export function ProgressBar({ value, tone = 'info', className = '', indeterminate = false }) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  return (
    <div className={`w-full h-1.5 bg-surface-highest rounded-full overflow-hidden ${className}`}>
      <div
        className={`h-full rounded-full transition-[width] duration-500 ${BAR_CLASSES[tone] ?? BAR_CLASSES.info} ${indeterminate ? 'animate-pulse w-full opacity-50' : ''}`}
        style={indeterminate ? undefined : { width: `${pct}%` }}
      />
    </div>
  );
}

export function LoadingBlock({ label = 'Cargando…', className = '' }) {
  return (
    <div className={`flex items-center justify-center gap-2 py-10 text-on-surface-variant text-xs ${className}`}>
      <Spinner />
      {label}
    </div>
  );
}

export function EmptyState({ icon = 'inbox', title, children, action, className = '' }) {
  return (
    <div className={`text-center py-10 px-4 text-on-surface-variant ${className}`}>
      <Icon name={icon} className="text-3xl text-outline" />
      {title && <p className="text-sm font-bold text-on-surface mt-2">{title}</p>}
      {children && <div className="text-xs mt-1 max-w-md mx-auto">{children}</div>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

export function ErrorBanner({ error, onRetry, title = 'No se pudo cargar', className = '' }) {
  const info = describeError(error);
  if (!info) return null;
  return (
    <div
      role="alert"
      className={`flex items-start gap-3 rounded-xl border border-error/30 bg-error-container/20 px-4 py-3 ${className}`}
    >
      <Icon name={info.status === 0 || error?.offline ? 'cloud_off' : 'error'} className="text-error mt-0.5" />
      <div className="flex-1 min-w-0">
        <p className="text-xs font-bold text-error">
          {title}
          {info.status ? <span className="font-mono font-normal opacity-80"> · {info.status}</span> : null}
        </p>
        <p className="text-xs text-on-surface mt-0.5 break-words">{info.detail}</p>
        {info.hint && <p className="text-[11px] text-on-surface-variant mt-1">{info.hint}</p>}
      </div>
      {onRetry && (
        <Button size="sm" variant="ghost" icon="refresh" onClick={onRetry}>
          Reintentar
        </Button>
      )}
    </div>
  );
}

export function Notice({ tone = 'warn', icon = 'info', children, className = '' }) {
  const toneCls = {
    warn: 'border-amber-400/30 bg-amber-400/10 text-amber-200',
    info: 'border-primary/30 bg-primary/10 text-primary',
    ok: 'border-tertiary/30 bg-tertiary/10 text-tertiary',
    error: 'border-error/30 bg-error-container/20 text-error',
  }[tone];
  return (
    <div className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-xs ${toneCls} ${className}`}>
      <Icon name={icon} className="text-sm mt-px" />
      <div className="flex-1 min-w-0">{children}</div>
    </div>
  );
}

export function Field({ label, hint, error, children, className = '' }) {
  const id = useId();
  return (
    <div className={className}>
      {label && (
        <label htmlFor={id} className={labelCls}>
          {label}
        </label>
      )}
      {typeof children === 'function' ? children(id) : children}
      {error ? (
        <p className="text-[10px] text-error mt-1">{error}</p>
      ) : hint ? (
        <p className="text-[10px] text-on-surface-variant mt-1">{hint}</p>
      ) : null}
    </div>
  );
}

export function Tabs({ tabs, value, onChange, className = '' }) {
  return (
    <div role="tablist" className={`flex flex-wrap gap-1 bg-surface-low rounded-lg p-1 ${className}`}>
      {tabs.map((t) => {
        const active = t.id === value;
        return (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(t.id)}
            className={`font-headline text-[10px] font-bold uppercase tracking-wider px-3 py-1.5 rounded-md cursor-pointer transition-colors flex items-center gap-1.5 ${
              active ? 'bg-surface-highest text-on-surface' : 'text-on-surface-variant hover:text-on-surface'
            }`}
          >
            {t.icon && <Icon name={t.icon} className="text-sm" />}
            {t.label}
            {t.count !== undefined && t.count !== null && (
              <span className={`font-mono ${active ? 'text-primary' : 'opacity-70'}`}>{t.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function Modal({ open, title, onClose, children, footer, wide = false }) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <button
        type="button"
        aria-label="Cerrar"
        className="absolute inset-0 bg-surface-dim/80 backdrop-blur-sm cursor-default"
        onClick={onClose}
      />
      <div
        className={`relative w-full ${wide ? 'max-w-2xl' : 'max-w-md'} bg-surface-container rounded-xl border border-outline-variant/20 shadow-2xl`}
      >
        <div className="px-5 py-3 border-b border-outline-variant/10 flex items-center justify-between">
          <h3 className="font-headline text-xs font-bold tracking-widest uppercase">{title}</h3>
          <button type="button" onClick={onClose} className="text-on-surface-variant hover:text-on-surface cursor-pointer">
            <Icon name="close" className="text-lg" />
          </button>
        </div>
        <div className="p-5 max-h-[70vh] overflow-y-auto">{children}</div>
        {footer && <div className="px-5 py-3 border-t border-outline-variant/10 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>
  );
}

export function Stat({ label, value, icon, sub }) {
  return (
    <div className="bg-surface-container rounded-xl p-4 border border-outline-variant/10">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">{label}</span>
        {icon && <Icon name={icon} className="text-sm text-primary" />}
      </div>
      <div className="font-headline text-2xl font-black">{value}</div>
      {sub && <div className="text-[10px] text-on-surface-variant mt-1">{sub}</div>}
    </div>
  );
}
