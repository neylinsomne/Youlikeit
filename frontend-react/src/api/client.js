const TWICK_BASE = '/api';
const PIPELINE_BASE = '/api';

export async function fetchClips(params = {}) {
  const query = new URLSearchParams(params).toString();
  const res = await fetch(`${TWICK_BASE}/clips?${query}`);
  return res.json();
}

export async function fetchCategories() {
  const res = await fetch(`${TWICK_BASE}/categories`);
  return res.json();
}

export async function fetchSeries() {
  const res = await fetch(`${TWICK_BASE}/series`);
  return res.json();
}

export async function fetchQuotes(params = {}) {
  const query = new URLSearchParams(params).toString();
  const res = await fetch(`${TWICK_BASE}/quotes?${query}`);
  return res.json();
}

export async function submitRender(clipIds, outputName) {
  const res = await fetch(`${TWICK_BASE}/render`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ clip_ids: clipIds, output_name: outputName }),
  });
  return res.json();
}

export async function fetchRenderQueue() {
  const res = await fetch(`${TWICK_BASE}/render/queue`);
  return res.json();
}

export async function sendToReview(videoPath) {
  const res = await fetch(`${TWICK_BASE}/send-to-review`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ video_path: videoPath }),
  });
  return res.json();
}

export async function triggerPipeline(pipeline, params = {}) {
  const res = await fetch(`${PIPELINE_BASE}/pipeline/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pipeline, params }),
  });
  return res.json();
}

export async function fetchPipelineStatus() {
  const res = await fetch(`${PIPELINE_BASE}/status`);
  return res.json();
}
