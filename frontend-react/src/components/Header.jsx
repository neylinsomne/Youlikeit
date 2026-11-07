import { useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { api } from '../api/client';
import { useApi } from '../hooks/useApi';
import { useSocketStatus } from '../hooks/useJobsSocket';
import { describeError } from '../lib/errors';
import { titleFor } from '../lib/nav';
import { Icon } from './ui';

const SOCKET_TEXT = {
  open: { label: 'Tiempo real', dot: 'bg-tertiary', title: 'WebSocket conectado: los trabajos se actualizan solos.' },
  connecting: { label: 'Conectando…', dot: 'bg-amber-300 animate-pulse', title: 'Abriendo el WebSocket /ws.' },
  closed: { label: 'Reconectando…', dot: 'bg-error animate-pulse', title: 'WebSocket caído: reintento con espera creciente.' },
  idle: { label: 'Sin tiempo real', dot: 'bg-outline', title: 'WebSocket inactivo.' },
};

function useHealth() {
  const health = useApi((signal) => api.health({ signal }), []);
  const { refetch } = health;
  useEffect(() => {
    const t = setInterval(refetch, 20000);
    return () => clearInterval(t);
  }, [refetch]);
  return health;
}

export default function Header() {
  const { pathname } = useLocation();
  const health = useHealth();
  const socket = useSocketStatus();
  const ws = SOCKET_TEXT[socket] ?? SOCKET_TEXT.idle;

  const apiOk = health.data?.ok === true && !health.error;
  const apiChecking = health.loading && health.data === undefined && !health.error;
  const apiTitle = apiOk
    ? 'API del estudio respondiendo en 127.0.0.1'
    : describeError(health.error)?.hint ?? 'Comprobando la API…';

  return (
    <header className="fixed top-0 right-0 left-64 z-50 h-16 bg-surface/80 backdrop-blur-xl flex items-center justify-between gap-6 px-8 border-b border-outline-variant/15 shadow-[0_4px_24px_rgba(0,0,0,0.4)]">
      <div className="min-w-0">
        <p className="text-[10px] uppercase tracking-[0.2em] text-on-surface-variant font-bold">Estudio local</p>
        <h2 className="font-headline text-sm font-bold truncate">{titleFor(pathname)}</h2>
      </div>

      <div className="flex items-center gap-4">
        <span
          title={apiTitle}
          className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant"
        >
          <span
            className={`h-2 w-2 rounded-full ${apiOk ? 'bg-tertiary' : apiChecking ? 'bg-amber-300 animate-pulse' : 'bg-error'}`}
          />
          {apiOk ? 'API conectada' : apiChecking ? 'Comprobando API' : 'API sin conexión'}
        </span>
        <span
          title={ws.title}
          className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant"
        >
          <span className={`h-2 w-2 rounded-full ${ws.dot}`} />
          {ws.label}
        </span>
        <div className="h-8 w-px bg-outline-variant/30" />
        <Link
          to="/editor?nueva=1"
          className="font-headline bg-linear-to-br from-primary to-primary-glow text-on-primary px-4 py-2 rounded-lg font-bold text-xs uppercase tracking-widest active:scale-95 transition-transform flex items-center gap-1.5"
        >
          <Icon name="add" className="text-sm" />
          Nueva lección
        </Link>
      </div>
    </header>
  );
}
