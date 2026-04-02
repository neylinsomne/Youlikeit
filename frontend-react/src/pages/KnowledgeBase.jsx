import { useState } from 'react';
import Layout from '../components/Layout';

const categories = [
  { id: 'all', label: 'All', icon: 'library_books' },
  { id: 'insight', label: 'Insights', icon: 'lightbulb' },
  { id: 'pattern', label: 'Patterns', icon: 'pattern' },
  { id: 'rule', label: 'Rules', icon: 'gavel' },
  { id: 'success', label: 'Successes', icon: 'emoji_events' },
  { id: 'mistake', label: 'Mistakes', icon: 'warning' },
];

const topics = [
  { id: 'all', label: 'All Topics' },
  { id: 'content', label: 'Content' },
  { id: 'audience', label: 'Audience' },
  { id: 'timing', label: 'Timing' },
  { id: 'hashtags', label: 'Hashtags' },
  { id: 'editing', label: 'Editing' },
];

export default function KnowledgeBase() {
  const [activeCategory, setActiveCategory] = useState('all');
  const [activeTopic, setActiveTopic] = useState('all');

  return (
    <Layout title="Knowledge Base">
      <div className="flex items-end justify-between mb-8">
        <div>
          <h2 className="text-3xl font-black tracking-tighter uppercase mb-1" style={{ fontFamily: 'var(--font-headline)' }}>
            Knowledge Base
          </h2>
          <p className="text-sm text-on-surface-variant">Insights, patterns, and learned rules from the pipeline</p>
        </div>
        <button className="bg-primary-glow/10 text-primary-glow px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-wider flex items-center gap-2 border border-primary-glow/20 cursor-pointer hover:bg-primary-glow/20 transition-colors">
          <span className="material-symbols-outlined text-sm">add</span>
          Add Entry
        </button>
      </div>

      <div className="grid grid-cols-12 gap-6">
        {/* Sidebar filters */}
        <div className="col-span-12 lg:col-span-3 space-y-4">
          <div className="bg-surface-container rounded-xl p-4 border border-outline-variant/10">
            <h3 className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-3">Category</h3>
            <div className="space-y-1">
              {categories.map((cat) => (
                <button
                  key={cat.id}
                  onClick={() => setActiveCategory(cat.id)}
                  className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                    activeCategory === cat.id
                      ? 'bg-primary-glow/10 text-primary-glow'
                      : 'text-on-surface-variant hover:bg-surface-high'
                  }`}
                >
                  <span className="material-symbols-outlined text-sm">{cat.icon}</span>
                  {cat.label}
                </button>
              ))}
            </div>
          </div>

          <div className="bg-surface-container rounded-xl p-4 border border-outline-variant/10">
            <h3 className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-3">Topic</h3>
            <div className="flex flex-wrap gap-2">
              {topics.map((topic) => (
                <button
                  key={topic.id}
                  onClick={() => setActiveTopic(topic.id)}
                  className={`px-3 py-1 rounded-full text-[10px] font-bold uppercase transition-all cursor-pointer ${
                    activeTopic === topic.id
                      ? 'bg-tertiary/20 text-tertiary'
                      : 'bg-surface-highest text-on-surface-variant hover:text-on-surface'
                  }`}
                >
                  {topic.label}
                </button>
              ))}
            </div>
          </div>

          <div className="bg-surface-container rounded-xl p-4 border border-outline-variant/10">
            <h3 className="text-[10px] font-bold uppercase tracking-widest text-on-surface-variant mb-3">Stats</h3>
            <div className="space-y-3">
              <div className="flex justify-between text-xs">
                <span className="text-on-surface-variant">Total entries</span>
                <span className="font-bold">0</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-on-surface-variant">High confidence</span>
                <span className="font-bold text-tertiary">0</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-on-surface-variant">From A/B tests</span>
                <span className="font-bold text-primary">0</span>
              </div>
            </div>
          </div>
        </div>

        {/* Main content */}
        <div className="col-span-12 lg:col-span-9">
          <div className="text-center py-20 text-on-surface-variant">
            <span className="material-symbols-outlined text-6xl mb-4">school</span>
            <h3 className="text-lg font-bold mb-2" style={{ fontFamily: 'var(--font-headline)' }}>Knowledge Base Empty</h3>
            <p className="text-sm max-w-md mx-auto">
              As the pipeline runs and learns from analytics, insights, patterns, and rules will be stored here automatically.
              You can also add entries manually.
            </p>
            <div className="mt-6 flex gap-3 justify-center">
              <button className="bg-surface-container border border-outline-variant/20 px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-wider cursor-pointer hover:bg-surface-high transition-colors">
                <span className="material-symbols-outlined text-sm mr-1 align-middle">play_arrow</span>
                Run Learning Cycle
              </button>
              <button className="bg-primary-glow/10 text-primary-glow border border-primary-glow/20 px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-wider cursor-pointer hover:bg-primary-glow/20 transition-colors">
                <span className="material-symbols-outlined text-sm mr-1 align-middle">upload_file</span>
                Import Knowledge
              </button>
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}
