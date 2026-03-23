/**
 * YouLikeIt Asset Server + Render Queue
 *
 * Serves clips from clip_library (SQLite) to the frontend editor.
 * Provides API for:
 *   - Browse/search clips by category, emotion, series
 *   - Serve panel images and audio files
 *   - Queue render jobs (FFmpeg concat + audio merge)
 *   - List render queue / download rendered videos
 *
 * Connects to the same shorts_pipeline.db that the Python pipeline uses.
 */

const express = require('express');
const cors = require('cors');
const path = require('path');
const fs = require('fs');
const { execSync, spawn } = require('child_process');

const app = express();
app.use(cors());
app.use(express.json());

// --- Database connection ---
const Database = require('better-sqlite3');
const DB_PATH = process.env.DB_PATH || '/app/data/shorts_pipeline.db';
let db;

function getDb() {
  if (!db) {
    db = new Database(DB_PATH, { readonly: true });
    db.pragma('journal_mode = WAL');
  }
  return db;
}

// --- Static file serving for clips ---
app.use('/files', express.static('/app/outputs'));
app.use('/panels', express.static('/app/data/manga_panels'));

// --- API: List clips ---
app.get('/api/clips', (req, res) => {
  const { category, emotion, source_type, search, limit = 50, offset = 0 } = req.query;
  const db = getDb();

  let where = [];
  let params = [];

  if (category) { where.push('category = ?'); params.push(category); }
  if (emotion) { where.push('emotion = ?'); params.push(emotion); }
  if (source_type) { where.push('source_type = ?'); params.push(source_type); }
  if (search) {
    where.push('(title LIKE ? OR quote_text LIKE ? OR ocr_text LIKE ? OR tags LIKE ?)');
    params.push(`%${search}%`, `%${search}%`, `%${search}%`, `%${search}%`);
  }

  const whereClause = where.length ? `WHERE ${where.join(' AND ')}` : '';
  const rows = db.prepare(
    `SELECT * FROM clip_library ${whereClause} ORDER BY times_used DESC, created_at DESC LIMIT ? OFFSET ?`
  ).all(...params, parseInt(limit), parseInt(offset));

  // Add serving URLs
  rows.forEach(r => {
    if (r.file_path) {
      r.image_url = `/files/${path.relative('/app/outputs', r.file_path)}`;
      // If file is under data/, serve from panels
      if (r.file_path.includes('manga_panels')) {
        r.image_url = `/panels/${path.relative('/app/data/manga_panels', r.file_path)}`;
      }
    }
    if (r.audio_path) {
      r.audio_url = `/files/${path.relative('/app/outputs', r.audio_path)}`;
    }
  });

  res.json({ clips: rows, total: rows.length });
});

// --- API: Get single clip ---
app.get('/api/clips/:id', (req, res) => {
  const db = getDb();
  const row = db.prepare('SELECT * FROM clip_library WHERE id = ?').get(req.params.id);
  if (!row) return res.status(404).json({ error: 'Clip not found' });
  res.json(row);
});

// --- API: List categories ---
app.get('/api/categories', (req, res) => {
  const db = getDb();
  const rows = db.prepare(
    'SELECT category, COUNT(*) as count FROM clip_library WHERE category IS NOT NULL GROUP BY category ORDER BY count DESC'
  ).all();
  res.json(rows);
});

// --- API: List manga series ---
app.get('/api/series', (req, res) => {
  const db = getDb();
  const rows = db.prepare(
    'SELECT id, title, media_type, score, popularity, genres, cover_url FROM manga_series ORDER BY composite_score DESC LIMIT 50'
  ).all();
  res.json(rows);
});

// --- API: List manga quotes ---
app.get('/api/quotes', (req, res) => {
  const { series_id, category, limit = 50 } = req.query;
  const db = getDb();

  let where = [];
  let params = [];
  if (series_id) { where.push('mq.series_id = ?'); params.push(series_id); }
  if (category) { where.push('mq.category = ?'); params.push(category); }

  const whereClause = where.length ? `WHERE ${where.join(' AND ')}` : '';
  const rows = db.prepare(
    `SELECT mq.*, ms.title as series_title FROM manga_quotes mq
     JOIN manga_series ms ON mq.series_id = ms.id
     ${whereClause} ORDER BY mq.viral_score DESC LIMIT ?`
  ).all(...params, parseInt(limit));

  res.json(rows);
});

// --- API: Render queue ---
const renderQueue = [];
const renderResults = [];

app.post('/api/render', (req, res) => {
  const { clip_ids, audio_intro, audio_outro, output_name } = req.body;

  if (!clip_ids || !clip_ids.length) {
    return res.status(400).json({ error: 'clip_ids required' });
  }

  const job = {
    id: Date.now().toString(36),
    clip_ids,
    audio_intro,
    audio_outro,
    output_name: output_name || `short_${Date.now()}`,
    status: 'queued',
    created_at: new Date().toISOString(),
  };

  renderQueue.push(job);
  processRenderQueue();

  res.json({ job_id: job.id, status: 'queued' });
});

app.get('/api/render/queue', (req, res) => {
  res.json({ queue: renderQueue, results: renderResults });
});

function processRenderQueue() {
  const job = renderQueue.find(j => j.status === 'queued');
  if (!job) return;

  job.status = 'rendering';
  const db = getDb();

  // Get clip file paths
  const clips = job.clip_ids.map(id => {
    const row = db.prepare('SELECT file_path FROM clip_library WHERE id = ?').get(id);
    return row ? row.file_path : null;
  }).filter(Boolean);

  if (!clips.length) {
    job.status = 'failed';
    job.error = 'No valid clips found';
    return;
  }

  // Build FFmpeg concat
  const outDir = '/app/outputs/renders';
  if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

  const outputPath = path.join(outDir, `${job.output_name}.mp4`);
  const concatFile = `/tmp/concat_${job.id}.txt`;

  // Create image-to-video clips and concat
  const tempClips = clips.map((clipPath, i) => {
    const tempOut = `/tmp/clip_${job.id}_${i}.mp4`;
    try {
      execSync(
        `ffmpeg -y -loop 1 -i "${clipPath}" -vf "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,zoompan=z='min(zoom+0.001,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=75:s=1080x1920:fps=25" -t 3 -c:v libx264 -preset fast -pix_fmt yuv420p "${tempOut}"`,
        { timeout: 30000, stdio: 'pipe' }
      );
      return tempOut;
    } catch (e) {
      return null;
    }
  }).filter(Boolean);

  if (!tempClips.length) {
    job.status = 'failed';
    job.error = 'FFmpeg failed on all clips';
    return;
  }

  // Concat
  fs.writeFileSync(concatFile, tempClips.map(c => `file '${c}'`).join('\n'));
  try {
    execSync(
      `ffmpeg -y -f concat -safe 0 -i "${concatFile}" -c:v libx264 -preset fast -pix_fmt yuv420p "${outputPath}"`,
      { timeout: 60000, stdio: 'pipe' }
    );
    job.status = 'completed';
    job.output_path = outputPath;
    job.output_url = `/files/renders/${job.output_name}.mp4`;
    renderResults.push(job);
  } catch (e) {
    job.status = 'failed';
    job.error = e.message;
  }

  // Cleanup temp files
  tempClips.forEach(f => { try { fs.unlinkSync(f); } catch {} });
  try { fs.unlinkSync(concatFile); } catch {}
}

// --- API: Upload to Clapshot review ---
app.post('/api/send-to-review', (req, res) => {
  const { video_path } = req.body;
  if (!video_path || !fs.existsSync(video_path)) {
    return res.status(400).json({ error: 'Video not found' });
  }

  // Copy to Clapshot incoming folder
  const incomingDir = '/app/outputs/shorts';
  if (!fs.existsSync(incomingDir)) fs.mkdirSync(incomingDir, { recursive: true });

  const dest = path.join(incomingDir, path.basename(video_path));
  fs.copyFileSync(video_path, dest);

  res.json({ status: 'sent_to_review', clapshot_url: 'http://localhost:8085/' });
});

// --- Health check ---
app.get('/health', (req, res) => {
  try {
    const db = getDb();
    const count = db.prepare('SELECT COUNT(*) as n FROM clip_library').get();
    res.json({ status: 'ok', clips: count.n });
  } catch (e) {
    res.status(500).json({ status: 'error', message: e.message });
  }
});

// --- Start ---
const PORT = process.env.PORT || 3000;
app.listen(PORT, '0.0.0.0', () => {
  console.log(`YouLikeIt Asset Server running on port ${PORT}`);
  console.log(`  Clips API:    http://localhost:${PORT}/api/clips`);
  console.log(`  Categories:   http://localhost:${PORT}/api/categories`);
  console.log(`  Render queue: http://localhost:${PORT}/api/render/queue`);
  console.log(`  Health:       http://localhost:${PORT}/health`);

  try {
    const db = getDb();
    const count = db.prepare('SELECT COUNT(*) as n FROM clip_library').get();
    console.log(`  Clips in library: ${count.n}`);
  } catch (e) {
    console.log(`  DB not yet available: ${e.message}`);
  }
});
