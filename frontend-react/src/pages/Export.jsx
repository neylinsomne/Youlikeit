import { useState } from 'react';
import Layout from '../components/Layout';

const exportOptions = [
  { id: 'csv', label: 'CSV', icon: 'table_chart', description: 'Movies, quotes, analytics, clips — spreadsheet compatible' },
  { id: 'json', label: 'JSON', icon: 'data_object', description: 'Full database export with nested relationships' },
  { id: 'backup', label: 'SQLite Backup', icon: 'database', description: 'Raw database file copy for disaster recovery' },
  { id: 'report', label: 'Channel Report', icon: 'summarize', description: 'PDF-ready summary with metrics, top performers, insights' },
];

export default function Export() {
  const [exporting, setExporting] = useState(null);
  const [history] = useState([]);

  const handleExport = (format) => {
    setExporting(format);
    setTimeout(() => setExporting(null), 2000);
  };

  return (
    <Layout title="Export">
      <div className="flex items-end justify-between mb-8">
        <div>
          <h2 className="text-3xl font-black tracking-tighter uppercase mb-1" style={{ fontFamily: 'var(--font-headline)' }}>
            Exportar
          </h2>
          <p className="text-sm text-on-surface-variant">Backup data, generate reports, export analytics</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8">
        {exportOptions.map(opt => (
          <div key={opt.id} className="bg-surface-container rounded-xl p-5 border border-outline-variant/10 hover:border-outline-variant/30 transition-all">
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-xl bg-surface-highest flex items-center justify-center flex-shrink-0">
                <span className="material-symbols-outlined text-primary">{opt.icon}</span>
              </div>
              <div className="flex-1">
                <h3 className="text-sm font-bold mb-1" style={{ fontFamily: 'var(--font-headline)' }}>{opt.label}</h3>
                <p className="text-[10px] text-on-surface-variant mb-3">{opt.description}</p>
                <button
                  onClick={() => handleExport(opt.id)}
                  disabled={exporting === opt.id}
                  className="bg-primary-glow/10 text-primary-glow px-4 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-wider cursor-pointer hover:bg-primary-glow/20 transition-colors disabled:opacity-40 flex items-center gap-1"
                >
                  {exporting === opt.id ? (
                    <>
                      <span className="material-symbols-outlined text-sm animate-spin">progress_activity</span>
                      Exporting...
                    </>
                  ) : (
                    <>
                      <span className="material-symbols-outlined text-sm">download</span>
                      Export
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="bg-surface-container rounded-xl border border-outline-variant/10">
        <div className="p-4 border-b border-outline-variant/10">
          <h3 className="text-xs font-bold tracking-widest uppercase" style={{ fontFamily: 'var(--font-headline)' }}>
            Export History
          </h3>
        </div>
        {history.length > 0 ? (
          <div className="divide-y divide-outline-variant/10">
            {history.map((h, i) => (
              <div key={i} className="p-4 flex items-center gap-3">
                <span className="material-symbols-outlined text-tertiary text-sm">check_circle</span>
                <span className="text-xs">{h.format}</span>
                <span className="text-[10px] text-on-surface-variant">{h.date}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-12 text-on-surface-variant">
            <span className="material-symbols-outlined text-3xl mb-2">folder_open</span>
            <p className="text-sm">No exports yet</p>
          </div>
        )}
      </div>
    </Layout>
  );
}
