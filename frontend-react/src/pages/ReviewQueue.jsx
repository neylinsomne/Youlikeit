import { useState, useEffect, useRef } from 'react';
import Layout from '../components/Layout';
import { fetchRenderQueue, sendToReview } from '../api/client';

const mockQueue = [
  {
    id: 'short_001',
    title: 'Berserk Ch.382 - Dark Philosophy',
    status: 'pending_review',
    duration: '28s',
    clips: 14,
    voice: 'Andrew (EN)',
    created: '2026-03-22 14:58',
    video_url: '/files/manga/Berserk_20260322_143056/BERSERK_ANDREW_v3.mp4',
    thumbnail: null,
    narration: {
      intro: 'What you\'re about to hear, you felt before you understood it',
      outro: 'Maybe that\'s why cinema never dies.',
    },
    metadata: {
      hashtags: '#Berserk #MangaEdit #AnimeQuotes #Shorts #DarkPhilosophy #YouLikeIt',
      song: 'Midnight Pulse - Lumina Wave',
      category: 'philosophical',
      emotion: 'determination',
    },
  },
];

function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function parseTime(str) {
  const parts = str.split(':');
  if (parts.length === 2) return parseInt(parts[0]) * 60 + parseInt(parts[1]);
  return parseInt(str) || 0;
}

function TimeInput({ value, onChange, max, label }) {
  const seconds = value || 0;
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[9px] text-on-surface-variant uppercase">{label}</span>
      <div className="flex items-center gap-2">
        <span className="text-xs font-mono text-on-surface w-12 text-center">{formatTime(seconds)}</span>
        <input
          type="range"
          min={0}
          max={max || 60}
          step={1}
          value={seconds}
          onChange={e => onChange(parseInt(e.target.value))}
          className="flex-1 h-1 accent-primary cursor-pointer"
        />
      </div>
    </div>
  );
}

function IssueMarker({ issue, onRemove }) {
  return (
    <div className="flex items-center gap-2 bg-error-container/20 border border-error/20 rounded-lg px-3 py-2">
      <span className="material-symbols-outlined text-error text-sm">
        {issue.type === 'voice' ? 'mic_off' : issue.type === 'image' ? 'broken_image' : issue.type === 'timing' ? 'timer_off' : 'warning'}
      </span>
      <div className="flex-1">
        <span className="text-[10px] font-bold text-error uppercase">{issue.type}</span>
        <span className="text-[10px] text-on-surface-variant ml-2">{formatTime(issue.start)} - {formatTime(issue.end)}</span>
        {issue.note && <span className="text-[10px] text-on-surface-variant ml-2">• {issue.note}</span>}
      </div>
      <button onClick={onRemove} className="text-on-surface-variant hover:text-error cursor-pointer">
        <span className="material-symbols-outlined text-sm">close</span>
      </button>
    </div>
  );
}

function ReviewCard({ short, onSelect, selected }) {
  const statusColors = {
    pending_review: 'bg-yellow-500/20 text-yellow-400 ring-yellow-500/30',
    approved: 'bg-tertiary/20 text-tertiary ring-tertiary/30',
    rejected: 'bg-error/20 text-error ring-error/30',
    uploaded: 'bg-primary/20 text-primary ring-primary/30',
  };
  const statusLabels = {
    pending_review: 'Pending Review',
    approved: 'Approved',
    rejected: 'Rejected',
    uploaded: 'Uploaded',
  };

  return (
    <div
      onClick={() => onSelect(short)}
      className={`bg-surface-container rounded-xl p-4 border cursor-pointer transition-all ${
        selected ? 'border-primary-glow/50 ring-1 ring-primary-glow/20' : 'border-outline-variant/10 hover:border-outline-variant/30'
      }`}
    >
      <div className="flex items-start gap-3">
        <div className="w-16 h-20 bg-surface-highest rounded-lg flex-shrink-0 flex items-center justify-center overflow-hidden">
          <span className="material-symbols-outlined text-2xl text-outline-variant">smart_display</span>
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs font-bold truncate">{short.title}</div>
          <div className="text-[10px] text-on-surface-variant mt-1">{short.duration} • {short.clips} clips • {short.voice}</div>
          <div className="flex items-center gap-2 mt-2">
            <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full ring-1 ${statusColors[short.status]}`}>
              {statusLabels[short.status]}
            </span>
            <span className="text-[9px] text-on-surface-variant">{short.created}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ReviewQueue() {
  const [queue, setQueue] = useState(mockQueue);
  const [selected, setSelected] = useState(mockQueue[0]);
  const [issues, setIssues] = useState([]);
  const [addingIssue, setAddingIssue] = useState(false);
  const [issueType, setIssueType] = useState('voice');
  const [issueStart, setIssueStart] = useState(0);
  const [issueEnd, setIssueEnd] = useState(0);
  const [issueNote, setIssueNote] = useState('');
  const [reviewNotes, setReviewNotes] = useState('');
  const videoRef = useRef(null);

  const videoDuration = parseInt(selected?.duration) || 30;

  const addIssue = () => {
    if (issueStart >= issueEnd) return;
    setIssues(prev => [...prev, {
      type: issueType,
      start: issueStart,
      end: issueEnd,
      note: issueNote,
    }]);
    setIssueStart(0);
    setIssueEnd(0);
    setIssueNote('');
    setAddingIssue(false);
  };

  const removeIssue = (index) => {
    setIssues(prev => prev.filter((_, i) => i !== index));
  };

  const handleApprove = () => {
    setQueue(prev => prev.map(s =>
      s.id === selected.id ? { ...s, status: 'approved' } : s
    ));
    setSelected(prev => ({ ...prev, status: 'approved' }));
  };

  const handleReject = () => {
    setQueue(prev => prev.map(s =>
      s.id === selected.id ? { ...s, status: 'rejected' } : s
    ));
    setSelected(prev => ({ ...prev, status: 'rejected' }));
  };

  const handleUpload = () => {
    setQueue(prev => prev.map(s =>
      s.id === selected.id ? { ...s, status: 'uploaded' } : s
    ));
    setSelected(prev => ({ ...prev, status: 'uploaded' }));
  };

  return (
    <Layout title="Review Queue">
      <div className="flex items-end justify-between mb-6">
        <div>
          <h2 className="text-3xl font-black tracking-tighter uppercase mb-1" style={{ fontFamily: 'var(--font-headline)' }}>
            Review Queue
          </h2>
          <p className="text-sm text-on-surface-variant">
            Review auto-generated shorts before publishing
          </p>
        </div>
        <div className="flex gap-3 text-xs">
          <span className="bg-yellow-500/10 text-yellow-400 px-3 py-1 rounded-full font-bold">
            {queue.filter(s => s.status === 'pending_review').length} Pending
          </span>
          <span className="bg-tertiary/10 text-tertiary px-3 py-1 rounded-full font-bold">
            {queue.filter(s => s.status === 'approved').length} Approved
          </span>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Queue list */}
        <div className="col-span-12 lg:col-span-3 space-y-3">
          <h3 className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-2" style={{ fontFamily: 'var(--font-headline)' }}>
            Queue ({queue.length})
          </h3>
          {queue.map(short => (
            <ReviewCard
              key={short.id}
              short={short}
              onSelect={setSelected}
              selected={selected?.id === short.id}
            />
          ))}
          {queue.length === 0 && (
            <div className="text-center py-12 text-on-surface-variant">
              <span className="material-symbols-outlined text-3xl">inbox</span>
              <p className="text-xs mt-2">No shorts to review</p>
            </div>
          )}
        </div>

        {/* Video preview + review */}
        {selected && (
          <div className="col-span-12 lg:col-span-6 space-y-4">
            {/* Video player */}
            <div className="bg-surface-container rounded-xl overflow-hidden border border-outline-variant/10">
              <div className="relative aspect-[9/16] max-h-[500px] bg-surface-dim mx-auto">
                <video
                  ref={videoRef}
                  className="w-full h-full object-contain"
                  controls
                  src={selected.video_url}
                />
              </div>
            </div>

            {/* Narration preview */}
            <div className="bg-surface-container rounded-xl p-4 border border-outline-variant/10">
              <h4 className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-3">Narration Script</h4>
              <div className="space-y-2">
                <div className="flex items-start gap-2">
                  <span className="bg-primary/20 text-primary text-[9px] font-bold px-2 py-0.5 rounded mt-0.5">INTRO</span>
                  <span className="text-xs text-on-surface italic">"{selected.narration.intro}"</span>
                </div>
                <div className="flex items-start gap-2">
                  <span className="bg-tertiary/20 text-tertiary text-[9px] font-bold px-2 py-0.5 rounded mt-0.5">OUTRO</span>
                  <span className="text-xs text-on-surface italic">"{selected.narration.outro}"</span>
                </div>
              </div>
            </div>

            {/* Issues */}
            <div className="bg-surface-container rounded-xl p-4 border border-outline-variant/10">
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant">
                  Issues ({issues.length})
                </h4>
                <button
                  onClick={() => setAddingIssue(!addingIssue)}
                  className="text-[10px] font-bold text-primary flex items-center gap-1 cursor-pointer"
                >
                  <span className="material-symbols-outlined text-sm">add</span>
                  Flag Issue
                </button>
              </div>

              {addingIssue && (
                <div className="bg-surface-highest rounded-lg p-4 mb-3 space-y-3">
                  <div className="flex gap-2">
                    {['voice', 'image', 'timing', 'other'].map(t => (
                      <button
                        key={t}
                        onClick={() => setIssueType(t)}
                        className={`text-[10px] font-bold px-3 py-1 rounded-full uppercase cursor-pointer ${
                          issueType === t ? 'bg-error/20 text-error' : 'bg-surface-container text-on-surface-variant'
                        }`}
                      >
                        {t}
                      </button>
                    ))}
                  </div>
                  <TimeInput label="Start" value={issueStart} onChange={setIssueStart} max={videoDuration} />
                  <TimeInput label="End" value={issueEnd} onChange={(v) => setIssueEnd(Math.max(v, issueStart + 1))} max={videoDuration} />
                  {issueStart < issueEnd && (
                    <div className="text-[10px] text-primary font-mono text-center">
                      Range: {formatTime(issueStart)} → {formatTime(issueEnd)} ({issueEnd - issueStart}s)
                    </div>
                  )}
                  {issueStart >= issueEnd && issueEnd > 0 && (
                    <div className="text-[10px] text-error text-center">End must be after start</div>
                  )}
                  <input
                    value={issueNote}
                    onChange={e => setIssueNote(e.target.value)}
                    placeholder="Describe the issue..."
                    className="w-full bg-surface-container border-none rounded-lg py-2 px-3 text-xs focus:ring-1 focus:ring-primary focus:outline-none"
                  />
                  <div className="flex gap-2 justify-end">
                    <button onClick={() => setAddingIssue(false)} className="text-on-surface-variant px-3 py-1.5 rounded-lg text-xs font-bold cursor-pointer hover:bg-surface-container">Cancel</button>
                    <button
                      onClick={addIssue}
                      disabled={issueStart >= issueEnd}
                      className="bg-error/20 text-error px-4 py-1.5 rounded-lg text-xs font-bold cursor-pointer disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                      Add Issue
                    </button>
                  </div>
                </div>
              )}

              <div className="space-y-2">
                {issues.map((issue, i) => (
                  <IssueMarker key={i} issue={issue} onRemove={() => removeIssue(i)} />
                ))}
                {issues.length === 0 && !addingIssue && (
                  <p className="text-[10px] text-on-surface-variant text-center py-2">No issues flagged</p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Right panel: metadata + actions */}
        {selected && (
          <div className="col-span-12 lg:col-span-3 space-y-4">
            {/* Metadata */}
            <div className="bg-surface-container rounded-xl p-4 border border-outline-variant/10">
              <h4 className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-3">Metadata</h4>
              <div className="space-y-3">
                <div>
                  <span className="text-[9px] text-on-surface-variant uppercase">Category</span>
                  <div className="text-xs font-bold text-primary capitalize">{selected.metadata.category}</div>
                </div>
                <div>
                  <span className="text-[9px] text-on-surface-variant uppercase">Emotion</span>
                  <div className="text-xs font-bold capitalize">{selected.metadata.emotion}</div>
                </div>
                <div>
                  <span className="text-[9px] text-on-surface-variant uppercase">Song (platform)</span>
                  <div className="text-xs font-bold text-tertiary">{selected.metadata.song}</div>
                </div>
                <div>
                  <span className="text-[9px] text-on-surface-variant uppercase">Hashtags</span>
                  <div className="text-[10px] text-primary">{selected.metadata.hashtags}</div>
                </div>
              </div>
            </div>

            {/* Review notes */}
            <div className="bg-surface-container rounded-xl p-4 border border-outline-variant/10">
              <h4 className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-3">Review Notes</h4>
              <textarea
                value={reviewNotes}
                onChange={e => setReviewNotes(e.target.value)}
                rows={4}
                className="w-full bg-surface-highest border-none rounded-lg py-2 px-3 text-xs focus:ring-1 focus:ring-primary focus:outline-none resize-none"
                placeholder="Add notes about this short..."
              />
            </div>

            {/* Actions */}
            <div className="space-y-2">
              {selected.status === 'pending_review' && (
                <>
                  <button
                    onClick={handleApprove}
                    className="w-full bg-tertiary/20 text-tertiary border border-tertiary/30 py-3 rounded-lg font-bold text-xs uppercase tracking-widest flex items-center justify-center gap-2 cursor-pointer hover:bg-tertiary/30 transition-colors"
                    style={{ fontFamily: 'var(--font-headline)' }}
                  >
                    <span className="material-symbols-outlined text-sm">check_circle</span>
                    Approve
                  </button>
                  <button
                    onClick={handleReject}
                    className="w-full bg-error-container/20 text-error border border-error/30 py-3 rounded-lg font-bold text-xs uppercase tracking-widest flex items-center justify-center gap-2 cursor-pointer hover:bg-error-container/30 transition-colors"
                    style={{ fontFamily: 'var(--font-headline)' }}
                  >
                    <span className="material-symbols-outlined text-sm">cancel</span>
                    Reject
                  </button>
                </>
              )}
              {selected.status === 'approved' && (
                <button
                  onClick={handleUpload}
                  className="w-full bg-linear-to-br from-primary to-primary-glow text-on-primary py-3 rounded-lg font-bold text-xs uppercase tracking-widest flex items-center justify-center gap-2 cursor-pointer active:scale-95 transition-transform"
                  style={{ fontFamily: 'var(--font-headline)' }}
                >
                  <span className="material-symbols-outlined text-sm">cloud_upload</span>
                  Upload to YouTube
                </button>
              )}
              {selected.status === 'uploaded' && (
                <div className="text-center py-3 text-tertiary">
                  <span className="material-symbols-outlined text-2xl" style={{ fontVariationSettings: "'FILL' 1" }}>check_circle</span>
                  <p className="text-xs font-bold mt-1">Uploaded Successfully</p>
                </div>
              )}
              {selected.status === 'rejected' && (
                <div className="text-center py-3 text-error">
                  <span className="material-symbols-outlined text-2xl">block</span>
                  <p className="text-xs font-bold mt-1">Rejected — Edit and re-render</p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </Layout>
  );
}
