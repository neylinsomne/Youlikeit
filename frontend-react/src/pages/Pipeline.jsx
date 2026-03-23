import { useState, useEffect } from 'react';
import Layout from '../components/Layout';
import { triggerPipeline } from '../api/client';

const pipelines = [
  { id: 'manga', label: 'Manga / Anime', icon: 'auto_stories', description: 'Discover trending manga, extract quotes, generate shorts', color: 'text-primary' },
  { id: 'movies', label: 'Movies / Series', icon: 'movie', description: 'Discover movies, download subtitles, match quotes', color: 'text-tertiary' },
  { id: 'learn', label: 'Learning Cycle', icon: 'school', description: 'Analyze performance, adjust weights, plan curriculum', color: 'text-secondary' },
];

function PipelineCard({ pipeline, onRun, running }) {
  return (
    <div className="bg-surface-container rounded-xl p-5 border border-outline-variant/10 hover:border-outline-variant/30 transition-all">
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-surface-highest flex items-center justify-center">
            <span className={`material-symbols-outlined ${pipeline.color}`}>{pipeline.icon}</span>
          </div>
          <div>
            <h3 className="text-sm font-bold" style={{ fontFamily: 'var(--font-headline)' }}>{pipeline.label}</h3>
            <p className="text-[10px] text-on-surface-variant">{pipeline.description}</p>
          </div>
        </div>
        <button
          onClick={() => onRun(pipeline.id)}
          disabled={running === pipeline.id}
          className="bg-primary-glow/10 text-primary-glow px-4 py-2 rounded-lg text-[10px] font-bold uppercase tracking-wider cursor-pointer hover:bg-primary-glow/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1"
        >
          {running === pipeline.id ? (
            <>
              <span className="material-symbols-outlined text-sm animate-spin">progress_activity</span>
              Running...
            </>
          ) : (
            <>
              <span className="material-symbols-outlined text-sm">play_arrow</span>
              Run
            </>
          )}
        </button>
      </div>
    </div>
  );
}

export default function Pipeline() {
  const [running, setRunning] = useState(null);
  const [runs, setRuns] = useState([]);
  const [stats, setStats] = useState(null);

  useEffect(() => {
    fetch('/api/status').then(r => r.ok ? r.json() : null).then(setStats).catch(() => {});
    fetch('/api/pipeline/runs').then(r => r.ok ? r.json() : null).then(d => setRuns(d?.data || [])).catch(() => {});
  }, []);

  const handleRun = async (pipelineId) => {
    setRunning(pipelineId);
    try {
      const result = await triggerPipeline(pipelineId);
      setRuns(prev => [{ id: result.run_id, pipeline: pipelineId, status: 'running', started_at: new Date().toISOString() }, ...prev]);
    } catch (e) {}
    setTimeout(() => setRunning(null), 3000);
  };

  return (
    <Layout title="Pipeline Control">
      <div className="flex items-end justify-between mb-8">
        <div>
          <h2 className="text-3xl font-black tracking-tighter uppercase mb-1" style={{ fontFamily: 'var(--font-headline)' }}>
            Pipeline
          </h2>
          <p className="text-sm text-on-surface-variant">Control and monitor automated content flows</p>
        </div>
      </div>

      {/* Quick stats */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-8">
        {[
          { label: 'Movies', value: stats?.movies ?? '-', icon: 'movie' },
          { label: 'Manga Series', value: stats?.manga_series ?? '-', icon: 'auto_stories' },
          { label: 'Quotes', value: stats?.quotes ?? '-', icon: 'format_quote' },
          { label: 'Clips', value: stats?.clip_library ?? '-', icon: 'collections' },
          { label: 'Shorts', value: stats?.shorts ?? '-', icon: 'bolt' },
        ].map((s) => (
          <div key={s.label} className="bg-surface-container rounded-xl p-4 border border-outline-variant/10">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest">{s.label}</span>
              <span className="material-symbols-outlined text-sm text-primary">{s.icon}</span>
            </div>
            <div className="text-xl font-black" style={{ fontFamily: 'var(--font-headline)' }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Pipeline cards */}
      <div className="mb-8">
        <h3 className="text-xs font-bold tracking-widest uppercase text-on-surface-variant mb-4" style={{ fontFamily: 'var(--font-headline)' }}>
          Available Pipelines
        </h3>
        <div className="space-y-3">
          {pipelines.map((p) => (
            <PipelineCard key={p.id} pipeline={p} onRun={handleRun} running={running} />
          ))}
        </div>
      </div>

      {/* Run history */}
      <div className="bg-surface-container rounded-xl border border-outline-variant/10">
        <div className="p-4 border-b border-outline-variant/10">
          <h3 className="text-xs font-bold tracking-widest uppercase" style={{ fontFamily: 'var(--font-headline)' }}>
            Recent Runs
          </h3>
        </div>
        <div className="divide-y divide-outline-variant/10">
          {runs.length > 0 ? runs.slice(0, 10).map((run, i) => (
            <div key={run.id || i} className="p-4 flex items-center gap-4">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center ${
                run.status === 'completed' ? 'bg-tertiary/20 text-tertiary' :
                run.status === 'running' ? 'bg-primary/20 text-primary' :
                run.status === 'failed' ? 'bg-error/20 text-error' : 'bg-surface-highest text-on-surface-variant'
              }`}>
                <span className="material-symbols-outlined text-sm">
                  {run.status === 'completed' ? 'check' : run.status === 'running' ? 'progress_activity' : run.status === 'failed' ? 'error' : 'schedule'}
                </span>
              </div>
              <div className="flex-1">
                <span className="text-xs font-bold capitalize">{run.pipeline}</span>
                <span className="text-[10px] text-on-surface-variant ml-2">{run.started_at}</span>
              </div>
              <span className={`text-[10px] font-bold uppercase ${
                run.status === 'completed' ? 'text-tertiary' : run.status === 'running' ? 'text-primary' : 'text-error'
              }`}>{run.status}</span>
            </div>
          )) : (
            <div className="text-center py-12 text-on-surface-variant">
              <span className="material-symbols-outlined text-3xl mb-2">history</span>
              <p className="text-sm">No pipeline runs yet</p>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}
