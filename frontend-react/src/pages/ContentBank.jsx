import { useState, useEffect } from 'react';
import Layout from '../components/Layout';
import { fetchClips, fetchSeries } from '../api/client';

const tabs = [
  { id: 'all', label: 'All', icon: 'grid_view' },
  { id: 'manga_panel', label: 'Manga', icon: 'auto_stories' },
  { id: 'anime', label: 'Anime', icon: 'animated_images' },
  { id: 'movie', label: 'Movies', icon: 'movie' },
  { id: 'comic', label: 'Comics', icon: 'menu_book' },
];

export default function ContentBank() {
  const [activeTab, setActiveTab] = useState('all');
  const [clips, setClips] = useState([]);
  const [series, setSeries] = useState([]);
  const [search, setSearch] = useState('');

  useEffect(() => {
    const params = {};
    if (activeTab !== 'all') params.source_type = activeTab;
    if (search) params.search = search;
    fetchClips({ ...params, limit: 50 }).then((d) => setClips(d.clips || []));
  }, [activeTab, search]);

  useEffect(() => {
    fetchSeries().then(setSeries).catch(() => {});
  }, []);

  return (
    <Layout title="Content Bank">
      <div className="flex items-end justify-between mb-8">
        <div>
          <h2 className="text-3xl font-black tracking-tighter uppercase mb-1" style={{ fontFamily: 'var(--font-headline)' }}>
            Contenido
          </h2>
          <p className="text-sm text-on-surface-variant">Banco de contenido extraido del pipeline</p>
        </div>
        <div className="relative">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant text-sm">search</span>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="bg-surface-container border-none rounded-full py-2 pl-10 pr-4 text-sm focus:ring-1 focus:ring-primary focus:outline-none"
            placeholder="Search content..."
          />
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-6">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-wider transition-all cursor-pointer ${
              activeTab === tab.id
                ? 'bg-primary-glow/10 text-primary-glow border border-primary-glow/30'
                : 'text-on-surface-variant hover:bg-surface-container'
            }`}
          >
            <span className="material-symbols-outlined text-sm">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Series carousel */}
      {series.length > 0 && (
        <div className="mb-6">
          <h3 className="text-xs font-bold tracking-widest uppercase mb-3 text-on-surface-variant" style={{ fontFamily: 'var(--font-headline)' }}>
            Series Discovered
          </h3>
          <div className="flex gap-3 overflow-x-auto pb-2">
            {series.map((s) => (
              <div key={s.id} className="flex-shrink-0 w-40 bg-surface-container rounded-xl p-3 border border-outline-variant/10 hover:border-primary/30 transition-all cursor-pointer">
                <div className="w-full aspect-[3/4] bg-surface-highest rounded-lg mb-2 overflow-hidden">
                  {s.cover_url ? (
                    <img src={s.cover_url} alt={s.title} className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <span className="material-symbols-outlined text-3xl text-outline-variant">image</span>
                    </div>
                  )}
                </div>
                <div className="text-xs font-bold truncate">{s.title}</div>
                <div className="text-[10px] text-on-surface-variant">{s.media_type} - {s.score}/10</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Clips grid */}
      <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-4">
        {clips.map((clip) => {
          const src = clip.file_path?.includes('manga_panels')
            ? `/panels/${clip.file_path.split('manga_panels/')[1] || ''}`
            : null;
          return (
            <div key={clip.id} className="bg-surface-container rounded-xl overflow-hidden border border-outline-variant/10 hover:border-primary/30 transition-all group">
              <div className="aspect-[3/4] bg-surface-highest">
                {src ? (
                  <img src={src} alt={clip.title} className="w-full h-full object-cover opacity-70 group-hover:opacity-100 transition-opacity" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <span className="material-symbols-outlined text-3xl text-outline-variant">image</span>
                  </div>
                )}
              </div>
              <div className="p-3">
                <div className="text-xs font-bold truncate">{clip.title?.split(' - ')[0] || 'Clip'}</div>
                <div className="text-[10px] text-on-surface-variant truncate">
                  {clip.category && <span className="text-primary">{clip.category}</span>}
                  {clip.ocr_text && <span> - {clip.ocr_text.slice(0, 30)}</span>}
                </div>
                {clip.quote_text && (
                  <div className="text-[10px] text-tertiary mt-1 truncate italic">"{clip.quote_text.slice(0, 40)}"</div>
                )}
                <div className="flex items-center justify-between mt-2">
                  <span className="text-[9px] text-on-surface-variant">p{clip.page_number}/panel {clip.panel_index}</span>
                  <span className="text-[9px] text-on-surface-variant">used: {clip.times_used}x</span>
                </div>
              </div>
            </div>
          );
        })}
        {clips.length === 0 && (
          <div className="col-span-full text-center py-16 text-on-surface-variant">
            <span className="material-symbols-outlined text-5xl mb-3">inbox</span>
            <p>No content yet. Run the pipeline to extract clips.</p>
          </div>
        )}
      </div>
    </Layout>
  );
}
