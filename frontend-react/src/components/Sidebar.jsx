import { Link, useLocation } from 'react-router-dom';

const navItems = [
  { path: '/', icon: 'rocket_launch', label: 'Pipeline' },
  { path: '/analytics', icon: 'monitoring', label: 'Analytics' },
  { path: '/content', icon: 'collections_bookmark', label: 'Contenido' },
  { path: '/shorts', icon: 'bolt', label: 'Shorts' },
  { path: '/review', icon: 'rate_review', label: 'Review' },
  { path: '/planner', icon: 'calendar_month', label: 'Planner' },
  { path: '/knowledge', icon: 'auto_stories', label: 'Knowledge Base' },
  { path: '/export', icon: 'ios_share', label: 'Exportar' },
];

export default function Sidebar({ onInitiateRun }) {
  const { pathname } = useLocation();

  return (
    <aside className="fixed left-0 top-0 h-full z-40 flex flex-col py-6 px-4 bg-surface-low w-64 border-r border-outline-variant/30">
      <div className="mb-10 px-2">
        <h1 className="text-xl font-black text-primary-glow tracking-tighter" style={{ fontFamily: 'var(--font-headline)' }}>
          YouLikeIt
        </h1>
        <p className="tracking-[0.2em] uppercase text-[10px] font-bold text-on-surface/40" style={{ fontFamily: 'var(--font-headline)' }}>
          Pro Pipeline
        </p>
      </div>

      <nav className="flex-1 space-y-1">
        {navItems.map((item) => {
          const active = pathname === item.path;
          return (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-all tracking-[0.15em] uppercase text-[10px] font-bold ${
                active
                  ? 'bg-primary-glow/10 text-primary-glow'
                  : 'text-on-surface/60 hover:text-on-surface hover:bg-surface-container'
              }`}
              style={{ fontFamily: 'var(--font-headline)' }}
            >
              <span className="material-symbols-outlined text-sm">{item.icon}</span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto space-y-4">
        <div className="p-3 bg-surface-container rounded-xl border border-outline-variant/15">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] font-bold text-tertiary uppercase tracking-widest">GPU Status</span>
            <span className="flex h-2 w-2 rounded-full bg-tertiary" />
          </div>
          <div className="text-xs font-bold" style={{ fontFamily: 'var(--font-headline)' }}>
            RTX 5060 <span className="text-on-surface-variant font-normal">Active</span>
          </div>
          <div className="w-full bg-surface-highest h-1 rounded-full mt-2 overflow-hidden">
            <div className="bg-tertiary h-full w-[42%]" />
          </div>
        </div>

        <button
          onClick={onInitiateRun}
          className="w-full bg-linear-to-br from-primary to-primary-glow text-on-primary py-3 rounded-lg font-bold text-xs uppercase tracking-widest active:scale-95 transition-transform cursor-pointer"
          style={{ fontFamily: 'var(--font-headline)' }}
        >
          Initiate Run
        </button>
      </div>
    </aside>
  );
}
