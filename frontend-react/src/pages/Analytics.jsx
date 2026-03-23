import { useState } from 'react';
import Layout from '../components/Layout';

const timeRanges = ['7d', '30d', '90d', 'All'];

export default function Analytics() {
  const [range, setRange] = useState('30d');

  return (
    <Layout title="Analytics">
      <div className="flex items-end justify-between mb-8">
        <div>
          <h2 className="text-3xl font-black tracking-tighter uppercase mb-1" style={{ fontFamily: 'var(--font-headline)' }}>
            Analytics
          </h2>
          <p className="text-sm text-on-surface-variant">Channel performance, retention, demographics, revenue</p>
        </div>
        <div className="flex gap-1 bg-surface-container rounded-lg p-1">
          {timeRanges.map(r => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`px-3 py-1.5 rounded text-[10px] font-bold uppercase cursor-pointer transition-colors ${
                range === r ? 'bg-primary-glow/20 text-primary-glow' : 'text-on-surface-variant hover:text-on-surface'
              }`}
            >
              {r}
            </button>
          ))}
        </div>
      </div>

      {/* Top metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        {[
          { label: 'Total Views', value: '0', change: '-', icon: 'visibility', color: 'text-primary' },
          { label: 'Engagement Rate', value: '0%', change: '-', icon: 'favorite', color: 'text-error' },
          { label: 'Avg Retention', value: '0%', change: '-', icon: 'hourglass_top', color: 'text-tertiary' },
          { label: 'Revenue', value: '$0.00', change: '-', icon: 'payments', color: 'text-secondary' },
        ].map(m => (
          <div key={m.label} className="bg-surface-container rounded-xl p-5 border border-outline-variant/10">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">{m.label}</span>
              <span className={`material-symbols-outlined text-sm ${m.color}`}>{m.icon}</span>
            </div>
            <div className="text-2xl font-black mb-1" style={{ fontFamily: 'var(--font-headline)' }}>{m.value}</div>
            <div className="text-[10px] text-on-surface-variant">{m.change}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Retention chart placeholder */}
        <div className="col-span-12 lg:col-span-8 bg-surface-container rounded-xl p-5 border border-outline-variant/10">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xs font-bold tracking-widest uppercase" style={{ fontFamily: 'var(--font-headline)' }}>
              Retention Curve (Avg)
            </h3>
            <span className="material-symbols-outlined text-primary text-sm">trending_up</span>
          </div>
          <div className="h-48 flex items-end gap-1 px-2">
            {Array.from({ length: 30 }, (_, i) => {
              const h = Math.max(10, 100 - i * 2.5 - Math.random() * 10);
              return (
                <div
                  key={i}
                  className="flex-1 rounded-t-sm transition-all hover:opacity-80"
                  style={{
                    height: `${h}%`,
                    background: h > 60 ? 'var(--color-tertiary)' : h > 30 ? 'var(--color-primary)' : 'var(--color-outline-variant)',
                  }}
                />
              );
            })}
          </div>
          <div className="flex justify-between mt-3 text-[10px] font-mono text-on-surface-variant">
            <span>0s</span><span>10s</span><span>20s</span><span>30s</span>
          </div>
          <div className="text-center mt-2 text-[10px] text-on-surface-variant">
            Publish shorts and run ex19 to see real retention data
          </div>
        </div>

        {/* Demographics */}
        <div className="col-span-12 lg:col-span-4 space-y-6">
          <div className="bg-surface-container rounded-xl p-5 border border-outline-variant/10">
            <h3 className="text-xs font-bold tracking-widest uppercase mb-4" style={{ fontFamily: 'var(--font-headline)' }}>
              Demographics
            </h3>
            <div className="space-y-3">
              {[
                { label: 'Gen Z (18-24)', pct: 0, color: 'bg-tertiary' },
                { label: 'Millennials (25-34)', pct: 0, color: 'bg-primary' },
                { label: 'Gen X (35-44)', pct: 0, color: 'bg-secondary' },
              ].map(d => (
                <div key={d.label}>
                  <div className="flex justify-between text-[10px] mb-1">
                    <span className="text-on-surface-variant">{d.label}</span>
                    <span className="font-bold">{d.pct}%</span>
                  </div>
                  <div className="w-full bg-surface-highest h-1.5 rounded-full overflow-hidden">
                    <div className={`${d.color} h-full rounded-full`} style={{ width: `${d.pct}%` }} />
                  </div>
                </div>
              ))}
              <p className="text-[10px] text-on-surface-variant text-center pt-2">Run ex26 to populate demographics</p>
            </div>
          </div>

          <div className="bg-surface-container rounded-xl p-5 border border-outline-variant/10">
            <h3 className="text-xs font-bold tracking-widest uppercase mb-4" style={{ fontFamily: 'var(--font-headline)' }}>
              Top Performing
            </h3>
            <div className="text-center py-6 text-on-surface-variant">
              <span className="material-symbols-outlined text-3xl mb-2">emoji_events</span>
              <p className="text-[10px]">Upload shorts to see rankings</p>
            </div>
          </div>
        </div>

        {/* Algorithm signals */}
        <div className="col-span-12 lg:col-span-6 bg-surface-container rounded-xl p-5 border border-outline-variant/10">
          <h3 className="text-xs font-bold tracking-widest uppercase mb-4" style={{ fontFamily: 'var(--font-headline)' }}>
            Algorithm Signals (Random Forest)
          </h3>
          <div className="space-y-3">
            {[
              { feature: 'hook_strength_3s', importance: 0 },
              { feature: 'category_match', importance: 0 },
              { feature: 'publish_hour', importance: 0 },
              { feature: 'hashtag_count', importance: 0 },
              { feature: 'duration_s', importance: 0 },
            ].map(f => (
              <div key={f.feature}>
                <div className="flex justify-between text-[10px] mb-1">
                  <span className="text-on-surface-variant font-mono">{f.feature}</span>
                  <span className="font-bold">{(f.importance * 100).toFixed(0)}%</span>
                </div>
                <div className="w-full bg-surface-highest h-1.5 rounded-full overflow-hidden">
                  <div className="bg-primary h-full rounded-full" style={{ width: `${f.importance * 100}%` }} />
                </div>
              </div>
            ))}
            <p className="text-[10px] text-on-surface-variant text-center pt-2">Run ex25 with real data to see feature importances</p>
          </div>
        </div>

        {/* Geo optimization */}
        <div className="col-span-12 lg:col-span-6 bg-surface-container rounded-xl p-5 border border-outline-variant/10">
          <h3 className="text-xs font-bold tracking-widest uppercase mb-4" style={{ fontFamily: 'var(--font-headline)' }}>
            Geographic Performance
          </h3>
          <div className="text-center py-8 text-on-surface-variant">
            <span className="material-symbols-outlined text-4xl mb-2">public</span>
            <p className="text-sm">Run ex27 to see country-level ANOVA</p>
          </div>
        </div>
      </div>
    </Layout>
  );
}
