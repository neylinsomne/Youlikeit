import { useState } from 'react';
import Layout from '../components/Layout';

const daysOfWeek = ['Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab', 'Dom'];

export default function Planner() {
  const [month] = useState(new Date().getMonth());
  const [year] = useState(new Date().getFullYear());

  const today = new Date().getDate();
  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const offset = firstDay === 0 ? 6 : firstDay - 1;

  const monthName = new Date(year, month).toLocaleDateString('es', { month: 'long', year: 'numeric' });

  return (
    <Layout title="Content Planner">
      <div className="flex items-end justify-between mb-8">
        <div>
          <h2 className="text-3xl font-black tracking-tighter uppercase mb-1" style={{ fontFamily: 'var(--font-headline)' }}>
            Planner
          </h2>
          <p className="text-sm text-on-surface-variant">Content calendar — schedule and track publications</p>
        </div>
        <button className="bg-primary-glow/10 text-primary-glow px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-wider flex items-center gap-2 border border-primary-glow/20 cursor-pointer hover:bg-primary-glow/20 transition-colors">
          <span className="material-symbols-outlined text-sm">auto_awesome</span>
          Auto-plan (ex33)
        </button>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Calendar */}
        <div className="col-span-12 lg:col-span-8 bg-surface-container rounded-xl p-5 border border-outline-variant/10">
          <h3 className="text-lg font-bold capitalize mb-4" style={{ fontFamily: 'var(--font-headline)' }}>
            {monthName}
          </h3>
          <div className="grid grid-cols-7 gap-1 mb-2">
            {daysOfWeek.map(d => (
              <div key={d} className="text-center text-[10px] font-bold text-on-surface-variant uppercase tracking-widest py-2">
                {d}
              </div>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-1">
            {Array.from({ length: offset }, (_, i) => (
              <div key={`empty-${i}`} className="aspect-square" />
            ))}
            {Array.from({ length: daysInMonth }, (_, i) => {
              const day = i + 1;
              const isToday = day === today;
              const isExcluded = day >= 15 && day <= 18;
              return (
                <div
                  key={day}
                  className={`aspect-square rounded-lg flex flex-col items-center justify-center text-xs cursor-pointer transition-all ${
                    isToday
                      ? 'bg-primary-glow/20 border-2 border-primary-glow text-primary-glow font-bold'
                      : isExcluded
                      ? 'bg-error-container/10 text-error/50 border border-error/10'
                      : 'bg-surface-highest hover:bg-surface-bright text-on-surface-variant'
                  }`}
                >
                  <span className="text-xs font-bold">{day}</span>
                  {isExcluded && <span className="text-[8px] mt-0.5">PAUSA</span>}
                </div>
              );
            })}
          </div>
          <div className="flex items-center gap-4 mt-4 text-[10px] text-on-surface-variant">
            <div className="flex items-center gap-1">
              <div className="w-3 h-3 rounded bg-primary-glow/20 border border-primary-glow" />
              <span>Today</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-3 h-3 rounded bg-error-container/10 border border-error/10" />
              <span>Pause (15-18)</span>
            </div>
            <div className="flex items-center gap-1">
              <div className="w-3 h-3 rounded bg-tertiary/30" />
              <span>Scheduled</span>
            </div>
          </div>
        </div>

        {/* Upcoming queue */}
        <div className="col-span-12 lg:col-span-4 space-y-4">
          <div className="bg-surface-container rounded-xl p-5 border border-outline-variant/10">
            <h3 className="text-xs font-bold tracking-widest uppercase mb-4" style={{ fontFamily: 'var(--font-headline)' }}>
              Upcoming
            </h3>
            <div className="text-center py-8 text-on-surface-variant">
              <span className="material-symbols-outlined text-3xl mb-2">event</span>
              <p className="text-[10px]">Run ex33 to generate curriculum plan</p>
              <p className="text-[10px] mt-1">Scheduled content will appear here</p>
            </div>
          </div>

          <div className="bg-surface-container rounded-xl p-5 border border-outline-variant/10">
            <h3 className="text-xs font-bold tracking-widest uppercase mb-4" style={{ fontFamily: 'var(--font-headline)' }}>
              Diversity Mix
            </h3>
            <div className="space-y-2">
              {['philosophical', 'villain', 'motivational', 'action', 'romantic'].map(cat => (
                <div key={cat} className="flex items-center justify-between">
                  <span className="text-[10px] text-on-surface-variant capitalize">{cat}</span>
                  <div className="w-24 bg-surface-highest h-1.5 rounded-full overflow-hidden">
                    <div className="bg-primary/40 h-full rounded-full" style={{ width: '0%' }} />
                  </div>
                </div>
              ))}
              <p className="text-[10px] text-on-surface-variant text-center pt-2">Balanced diversity ensures audience growth</p>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}
