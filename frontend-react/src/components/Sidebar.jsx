import { NavLink } from 'react-router-dom';
import { NAV_ITEMS } from '../lib/nav';
import { Icon } from './ui';

export default function Sidebar() {
  return (
    <aside className="fixed left-0 top-0 h-full z-40 flex flex-col py-6 px-4 bg-surface-low w-64 border-r border-outline-variant/30">
      <div className="mb-10 px-2">
        <h1 className="font-headline text-xl font-black text-primary-glow tracking-tighter">YouLikeIt</h1>
        <p className="font-headline tracking-[0.2em] uppercase text-[10px] font-bold text-on-surface/40">
          Estudio
        </p>
      </div>

      <nav className="flex-1 space-y-1" aria-label="Secciones del estudio">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              `font-headline flex items-center gap-3 px-3 py-2 rounded-lg transition-all tracking-[0.15em] uppercase text-[10px] font-bold ${
                isActive
                  ? 'bg-primary-glow/10 text-primary-glow'
                  : 'text-on-surface/60 hover:text-on-surface hover:bg-surface-container'
              }`
            }
          >
            <Icon name={item.icon} className="text-sm" />
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="mt-auto p-3 bg-surface-container rounded-xl border border-outline-variant/15 text-[10px] text-on-surface-variant space-y-1.5">
        <div className="flex items-center gap-1.5 text-on-surface font-bold uppercase tracking-widest">
          <Icon name="lock" className="text-sm text-tertiary" />
          Solo en esta PC
        </div>
        <p>Empatía a través del cine: momentos de películas de dominio público convertidos en lecciones cortas.</p>
        <p className="flex items-center gap-1">
          <Icon name="music_note" className="text-xs" />
          La música se elige en TikTok/YouTube.
        </p>
      </div>
    </aside>
  );
}
