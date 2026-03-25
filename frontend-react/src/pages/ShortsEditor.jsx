import { useState, useEffect } from 'react';
import Layout from '../components/Layout';
import { fetchClips, fetchTrendingMusic, fileUrl } from '../api/client';

const cameraIcons = {
  zoom_in: 'zoom_in',
  zoom_out: 'zoom_out',
  pan_left: 'arrow_back',
  pan_right: 'arrow_forward',
  pan_up: 'arrow_upward',
  pan_down: 'arrow_downward',
  zoom_pan_r: 'open_in_full',
  zoom_pan_l: 'open_in_full',
  dramatic: 'center_focus_strong',
};

function ClipCard({ clip, onAdd }) {
  const src = clip.file_path
    ? `/api/files/${clip.file_path}`
    : null;

  // Parse description JSON for camera move info
  let meta = {};
  try { meta = JSON.parse(clip.description || '{}'); } catch {}
  const cameraMove = meta.camera_move || clip.tags?.match(/"(zoom_in|zoom_out|pan_\w+|dramatic)"/)?.[1] || '';
  const hasMatch = meta.has_quote_match || !!clip.quote_text;

  return (
    <div
      className="group cursor-pointer relative rounded-lg overflow-hidden border border-outline-variant/10 hover:border-primary/40 transition-all"
      draggable
      onDragStart={(e) => e.dataTransfer.setData('clip_id', clip.id)}
      onClick={() => onAdd(clip)}
    >
      <div className="aspect-[3/4] bg-surface-highest relative">
        {src ? (
          <img src={src} alt={clip.title} className="w-full h-full object-cover opacity-70 group-hover:opacity-100 transition-opacity" />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-on-surface-variant">
            <span className="material-symbols-outlined text-3xl">image</span>
          </div>
        )}
        {/* Camera move badge */}
        {cameraMove && (
          <div className="absolute top-1 right-1 bg-surface/80 backdrop-blur rounded px-1 py-0.5 flex items-center gap-0.5">
            <span className="material-symbols-outlined text-primary" style={{ fontSize: '10px' }}>
              {cameraIcons[cameraMove] || 'videocam'}
            </span>
            <span className="text-[8px] text-primary font-mono">{cameraMove.replace('_', ' ')}</span>
          </div>
        )}
        {/* Quote match indicator */}
        {hasMatch && (
          <div className="absolute top-1 left-1 bg-tertiary/90 rounded px-1 py-0.5">
            <span className="text-[8px] text-on-tertiary font-bold">MATCH</span>
          </div>
        )}
      </div>
      <div className="absolute inset-0 bg-linear-to-t from-surface/90 via-transparent opacity-0 group-hover:opacity-100 transition-opacity flex flex-col items-start justify-end p-2">
        {clip.quote_text && (
          <p className="text-[9px] text-primary italic mb-1 line-clamp-2">"{clip.quote_text.slice(0, 60)}"</p>
        )}
        {clip.character_name && (
          <p className="text-[8px] text-tertiary">— {clip.character_name}</p>
        )}
        <span className="material-symbols-outlined text-primary text-lg mt-1">add_circle</span>
      </div>
      <div className="p-2">
        <div className="text-[10px] font-bold text-on-surface truncate">{clip.title?.split(' - ')[0] || 'Clip'}</div>
        <div className="text-[9px] text-on-surface-variant truncate">{clip.category || 'panel'}</div>
      </div>
    </div>
  );
}

function TimelineSlot({ clip, index, onRemove }) {
  let meta = {};
  try { meta = JSON.parse(clip.description || '{}'); } catch {}
  const cameraMove = meta.camera_move || '';
  const hasMatch = !!clip.quote_text;
  const dur = clip.duration_s || 2;

  return (
    <div className={`flex-shrink-0 w-44 h-20 rounded-lg flex flex-col justify-between p-2 relative group transition-all ${
      hasMatch
        ? 'bg-tertiary/10 border-2 border-tertiary/40'
        : 'bg-surface-high border-2 border-primary-glow/30'
    }`}>
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold text-on-surface truncate">
          {clip.title?.split('panel')[1] ? `Panel ${clip.title.split('panel')[1].trim()}` : `Clip ${index + 1}`}
        </span>
        <span className="text-[8px] font-mono text-on-surface-variant">{dur}s</span>
      </div>
      <div className="flex items-center gap-1">
        {cameraMove && (
          <span className="bg-primary/20 text-primary text-[8px] px-1.5 py-0.5 rounded font-mono">
            {cameraMove.replace('_', ' ')}
          </span>
        )}
        {hasMatch && (
          <span className="bg-tertiary/20 text-tertiary text-[8px] px-1.5 py-0.5 rounded font-bold">
            QUOTE
          </span>
        )}
      </div>
      {clip.quote_text && (
        <div className="text-[8px] text-tertiary italic truncate">
          "{clip.quote_text.slice(0, 35)}..."
        </div>
      )}
      <button
        onClick={() => onRemove(index)}
        className="opacity-0 group-hover:opacity-100 absolute -top-2 -right-2 w-5 h-5 bg-error-container rounded-full flex items-center justify-center text-error cursor-pointer"
      >
        <span className="material-symbols-outlined text-xs">close</span>
      </button>
    </div>
  );
}

function DropZone({ onDrop }) {
  const [over, setOver] = useState(false);

  return (
    <div
      className={`flex-shrink-0 w-36 h-16 rounded-lg border-2 border-dashed flex items-center justify-center transition-colors ${
        over ? 'border-primary-glow bg-primary-glow/10' : 'border-outline-variant/30'
      }`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const clipId = e.dataTransfer.getData('clip_id');
        if (clipId) onDrop(parseInt(clipId));
      }}
    >
      <span className="text-[10px] text-on-surface-variant">Drop here</span>
    </div>
  );
}

// Removed mock data — songs come from API

export default function ShortsEditor() {
  const [clips, setClips] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [filter, setFilter] = useState('all');
  const [selectedSong, setSelectedSong] = useState(0);
  const [title, setTitle] = useState('');
  const [hashtags, setHashtags] = useState('#AnimeEdit #MangaArt #Shorts #YouLikeIt');
  const [rendering, setRendering] = useState(false);
  const [previewIdx, setPreviewIdx] = useState(0);
  const [songs, setSongs] = useState([]);
  const [musicQuery, setMusicQuery] = useState('');

  useEffect(() => {
    fetchTrendingMusic('CO').then(data => setSongs(data.songs || []));
  }, []);

  const searchMusic = () => {
    if (musicQuery.trim()) {
      fetchTrendingMusic('CO', musicQuery).then(data => setSongs(data.songs || []));
    }
  };

  useEffect(() => {
    fetchClips({ per_page: 50 })
      .then((data) => {
        console.log('[YLI] Clips response:', data);
        setClips(data.items || data.clips || []);
      })
      .catch((e) => console.error('[YLI] Clips fetch error:', e));
  }, []);

  const addToTimeline = (clip) => {
    setTimeline((prev) => [...prev, clip]);
  };

  const removeFromTimeline = (index) => {
    setTimeline((prev) => prev.filter((_, i) => i !== index));
  };

  const handleDrop = (clipId) => {
    const clip = clips.find((c) => c.id === clipId);
    if (clip) addToTimeline(clip);
  };

  const handleRender = async () => {
    if (!timeline.length) return;
    setRendering(true);
    const ids = timeline.map((c) => c.id);
    const name = title.replace(/\s+/g, '_').toLowerCase() || `short_${Date.now()}`;
    // TODO: connect to render API
    console.log('Render:', ids, name);
    setRendering(false);
  };

  const filteredClips = filter === 'all'
    ? clips
    : clips.filter((c) => {
        const st = c.source_type || '';
        if (filter === 'manga') return st.includes('manga') || st.includes('anime');
        if (filter === 'movie') return st.includes('movie') || st.includes('video');
        return st.includes(filter);
      });

  return (
    <Layout title="Creative Studio">
      <div className="grid grid-cols-12 gap-6">
        {/* Main area */}
        <div className="col-span-12 lg:col-span-8 space-y-6">
          {/* Preview */}
          <div className="bg-surface-container rounded-xl overflow-hidden border border-outline-variant/10">
            <div className="aspect-[9/16] max-h-[480px] bg-surface-dim flex items-center justify-center relative mx-auto">
              {timeline.length > 0 ? (
                <>
                  <img
                    src={`/api/files/${timeline[previewIdx]?.file_path}`}
                    alt={timeline[previewIdx]?.title}
                    className="w-full h-full object-contain"
                  />
                  {timeline[previewIdx]?.quote_text && (
                    <div className="absolute bottom-4 left-4 right-4 bg-surface/80 backdrop-blur-sm rounded-lg p-3">
                      <p className="text-xs text-primary italic">"{timeline[previewIdx].quote_text.slice(0, 100)}"</p>
                      {timeline[previewIdx].character_name && (
                        <p className="text-[10px] text-tertiary mt-1">— {timeline[previewIdx].character_name}</p>
                      )}
                    </div>
                  )}
                </>
              ) : (
                <div className="text-center">
                  <span className="material-symbols-outlined text-5xl text-outline-variant">movie_edit</span>
                  <p className="text-xs text-on-surface-variant mt-2">Add clips to preview</p>
                </div>
              )}
              <div className="absolute top-4 left-4 bg-error/90 text-on-error text-[10px] font-bold px-3 py-1 rounded-full uppercase tracking-wider flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-on-error animate-pulse" />
                Live Preview
              </div>
              {timeline.length > 0 && (
                <div className="absolute top-4 right-4 bg-surface/70 backdrop-blur-sm text-xs text-on-surface font-mono px-2 py-1 rounded">
                  {previewIdx + 1} / {timeline.length} | ~{timeline.reduce((s, c) => s + (c.duration_s || 2), 0).toFixed(0)}s
                </div>
              )}
            </div>
            <div className="flex items-center justify-center gap-8 py-4 border-t border-outline-variant/10">
              <button
                onClick={() => setPreviewIdx((i) => Math.max(0, i - 1))}
                disabled={!timeline.length}
                className="text-on-surface hover:text-primary cursor-pointer disabled:opacity-30"
              >
                <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>skip_previous</span>
              </button>
              <button className="w-12 h-12 bg-primary text-on-primary rounded-full flex items-center justify-center hover:scale-105 cursor-pointer">
                <span className="material-symbols-outlined text-2xl" style={{ fontVariationSettings: "'FILL' 1" }}>play_arrow</span>
              </button>
              <button
                onClick={() => setPreviewIdx((i) => Math.min(timeline.length - 1, i + 1))}
                disabled={!timeline.length}
                className="text-on-surface hover:text-primary cursor-pointer disabled:opacity-30"
              >
                <span className="material-symbols-outlined" style={{ fontVariationSettings: "'FILL' 1" }}>skip_next</span>
              </button>
            </div>
          </div>

          {/* Clip Library */}
          <div className="bg-surface-container rounded-xl border border-outline-variant/10">
            <div className="p-4 border-b border-outline-variant/10 flex items-center justify-between">
              <h3 className="text-xs font-bold tracking-widest uppercase" style={{ fontFamily: 'var(--font-headline)' }}>
                Clip Library: Movie & Manga
              </h3>
              <div className="flex gap-2">
                {['all', 'movie', 'manga'].map((f) => (
                  <button
                    key={f}
                    onClick={() => setFilter(f)}
                    className={`text-[10px] font-bold px-3 py-1 rounded uppercase cursor-pointer ${
                      filter === f ? 'bg-surface-highest text-on-surface' : 'text-on-surface-variant'
                    }`}
                  >
                    {f === 'all' ? 'All' : f === 'movie' ? 'Movies' : 'Anime'}
                  </button>
                ))}
              </div>
            </div>
            <div className="p-4">
              <p className="text-[10px] text-on-surface-variant mb-2">
                Loaded: {clips.length} clips | Showing: {filteredClips.length} | Filter: {filter}
              </p>
              <div className="grid grid-cols-4 sm:grid-cols-5 md:grid-cols-6 gap-3 max-h-64 overflow-y-auto">
              {filteredClips.map((clip) => (
                <ClipCard key={clip.id} clip={clip} onAdd={addToTimeline} />
              ))}
              {filteredClips.length === 0 && (
                <div className="col-span-full text-center py-8 text-on-surface-variant text-sm">
                  No clips found. Run the pipeline first.
                </div>
              )}
            </div>
          </div>
          </div>

          {/* Timeline */}
          <div className="bg-surface-container rounded-xl p-4 border border-outline-variant/10">
            <div className="flex items-center gap-4 overflow-x-auto pb-2">
              {timeline.map((clip, i) => (
                <TimelineSlot key={`${clip.id}-${i}`} clip={clip} index={i} onRemove={removeFromTimeline} />
              ))}
              <DropZone onDrop={handleDrop} />
            </div>
            <div className="flex items-center justify-between mt-3">
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full ${timeline.length ? 'bg-tertiary' : 'bg-outline-variant'}`} />
                <span className="text-[10px] text-on-surface-variant">
                  {timeline.length ? 'Auto-saving local cache...' : 'Empty timeline'}
                </span>
              </div>
              <span className="text-[10px] text-on-surface-variant font-mono">
                {timeline.length} clips / ~{timeline.length * 3}s
              </span>
            </div>
          </div>
        </div>

        {/* Right panel */}
        <div className="col-span-12 lg:col-span-4 space-y-6">
          {/* Trending Music */}
          <div className="bg-surface-container rounded-xl p-5 border border-outline-variant/10">
            <h3 className="text-xs font-bold tracking-widest uppercase flex items-center gap-2 mb-3 text-primary" style={{ fontFamily: 'var(--font-headline)' }}>
              <span className="material-symbols-outlined text-sm">trending_up</span>
              YouTube Music Trending
            </h3>
            <div className="flex gap-2 mb-3">
              <input
                value={musicQuery}
                onChange={(e) => setMusicQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && searchMusic()}
                placeholder="Search songs..."
                className="flex-1 bg-surface-highest border-none rounded-lg py-1.5 px-2 text-[11px] text-on-surface focus:ring-1 focus:ring-primary focus:outline-none"
              />
              <button onClick={searchMusic} className="text-primary hover:text-primary-glow cursor-pointer">
                <span className="material-symbols-outlined text-sm">search</span>
              </button>
            </div>
            <div className="space-y-1.5 max-h-64 overflow-y-auto">
              {songs.map((song, i) => (
                <div
                  key={song.video_id || i}
                  onClick={() => setSelectedSong(i)}
                  className={`flex items-center gap-2 p-2 rounded-lg cursor-pointer transition-all ${
                    selectedSong === i
                      ? 'bg-primary-glow/10 border border-primary-glow/30'
                      : 'hover:bg-surface-high'
                  }`}
                >
                  {song.thumbnail ? (
                    <img src={song.thumbnail} alt="" className="w-9 h-9 rounded-lg object-cover flex-shrink-0" />
                  ) : (
                    <div className="w-9 h-9 rounded-lg bg-surface-highest flex items-center justify-center flex-shrink-0">
                      <span className="material-symbols-outlined text-primary text-sm">music_note</span>
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <div className="text-[11px] font-bold truncate">{song.title}</div>
                    <div className="text-[9px] text-on-surface-variant truncate">{song.artist} {song.duration && `· ${song.duration}`}</div>
                  </div>
                  {selectedSong === i ? (
                    <a href={song.youtube_url} target="_blank" rel="noreferrer"
                      className="text-primary hover:text-primary-glow" onClick={(e) => e.stopPropagation()}>
                      <span className="material-symbols-outlined text-sm">open_in_new</span>
                    </a>
                  ) : (
                    <span className="material-symbols-outlined text-outline-variant text-sm">add_circle</span>
                  )}
                </div>
              ))}
              {songs.length === 0 && (
                <p className="text-[10px] text-on-surface-variant text-center py-4">Loading trending songs...</p>
              )}
            </div>
            {selectedSong !== null && songs[selectedSong] && (
              <a href={songs[selectedSong].youtube_url} target="_blank" rel="noreferrer"
                className="mt-3 flex items-center justify-center gap-2 bg-surface-highest rounded-lg py-2 text-[10px] text-primary hover:text-primary-glow transition-colors">
                <span className="material-symbols-outlined text-sm">play_circle</span>
                Open in YouTube
              </a>
            )}
          </div>

          {/* Metadata Editor */}
          <div className="bg-surface-container rounded-xl p-5 border border-outline-variant/10">
            <h3 className="text-xs font-bold tracking-widest uppercase flex items-center gap-2 mb-4" style={{ fontFamily: 'var(--font-headline)' }}>
              <span className="material-symbols-outlined text-sm">tune</span>
              Metadata Editor
            </h3>
            <div className="space-y-4">
              <div>
                <label className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest block mb-2">Short Title</label>
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  className="w-full bg-surface-highest border-none rounded-lg py-2.5 px-3 text-sm text-on-surface focus:ring-1 focus:ring-primary focus:outline-none"
                  placeholder="The Rise of Neon: Chapter 1"
                />
              </div>
              <div>
                <label className="text-[10px] font-bold text-on-surface-variant uppercase tracking-widest block mb-2">Hashtags</label>
                <textarea
                  value={hashtags}
                  onChange={(e) => setHashtags(e.target.value)}
                  rows={3}
                  className="w-full bg-surface-highest border-none rounded-lg py-2.5 px-3 text-sm text-on-surface focus:ring-1 focus:ring-primary focus:outline-none resize-none"
                />
              </div>
            </div>
          </div>

          {/* Actions */}
          <button
            className="w-full bg-surface-container border border-outline-variant/20 py-3 rounded-lg font-bold text-xs uppercase tracking-widest flex items-center justify-center gap-2 hover:bg-surface-high transition-colors cursor-pointer"
            style={{ fontFamily: 'var(--font-headline)' }}
          >
            <span className="material-symbols-outlined text-sm">save</span>
            Guardar Progreso
          </button>

          <button
            onClick={handleRender}
            disabled={!timeline.length || rendering}
            className="w-full bg-linear-to-br from-primary to-primary-glow text-on-primary py-3 rounded-lg font-bold text-xs uppercase tracking-widest flex items-center justify-center gap-2 active:scale-95 transition-transform cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
            style={{ fontFamily: 'var(--font-headline)' }}
          >
            <span className="material-symbols-outlined text-sm">rocket_launch</span>
            {rendering ? 'Rendering...' : 'Subir y Revision Final'}
          </button>
        </div>
      </div>
    </Layout>
  );
}
