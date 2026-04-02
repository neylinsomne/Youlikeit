export default function Header({ title = 'Pipeline Lead' }) {
  return (
    <header className="fixed top-0 right-0 left-64 z-50 h-16 bg-surface/80 backdrop-blur-xl flex items-center justify-between px-8 border-b border-outline-variant/15 shadow-[0_4px_24px_rgba(0,0,0,0.4)]">
      <div className="flex items-center flex-1 max-w-xl">
        <div className="relative w-full group">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-sm group-focus-within:text-primary transition-colors">
            search
          </span>
          <input
            className="w-full bg-surface-low border-none rounded-full py-2 pl-10 pr-4 text-sm focus:ring-1 focus:ring-primary transition-all focus:outline-none"
            placeholder="Search assets..."
            type="text"
          />
        </div>
      </div>
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-4 text-on-surface-variant">
          <span className="material-symbols-outlined cursor-pointer hover:text-primary transition-colors">sensors</span>
          <span className="material-symbols-outlined cursor-pointer hover:text-primary transition-colors">notifications</span>
          <span className="material-symbols-outlined cursor-pointer hover:text-primary transition-colors">settings</span>
        </div>
        <div className="h-8 w-px bg-outline-variant/30" />
        <button className="bg-linear-to-br from-primary to-primary-glow text-on-primary px-5 py-2 rounded-lg font-bold text-xs uppercase tracking-widest active:scale-95 transition-transform cursor-pointer"
          style={{ fontFamily: 'var(--font-headline)' }}>
          Initiate Run
        </button>
      </div>
    </header>
  );
}
