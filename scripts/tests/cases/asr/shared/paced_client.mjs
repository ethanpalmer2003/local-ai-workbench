// Persistent transport worker. Python owns benchmark timing; no package dependency.
import http from 'node:http';
import readline from 'node:readline';
import {setTimeout as sleep} from 'node:timers/promises';

const emit = value => process.stdout.write(JSON.stringify(value) + '\n');
const bounded = (promise, ms = 15000) => {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error('Transport timeout')), ms);
  })]).finally(() => clearTimeout(timer));
};

async function feed(c, send) {
  const pcm = Buffer.from(c.pcm, 'base64');
  const chunkBytes = Math.round(c.rate * c.chunk_ms / 1000) * 2;
  const start = performance.now();
  emit({kind: 'audio_start'});
  for (let offset = 0; offset < pcm.length;) {
    const end = Math.min(offset + chunkBytes, offset < c.speech_bytes ? c.speech_bytes : pcm.length, pcm.length);
    const chunk = pcm.subarray(offset, end);
    if (c.paced) await sleep(Math.max(0, (offset + chunk.length) / (c.rate * 2) * 1000 - (performance.now() - start)));
    send(chunk);
    if (offset + chunk.length >= c.speech_bytes && offset < c.speech_bytes) {
      emit({kind: 'audio_end', elapsed_ms: performance.now() - start});
    }
    offset = end;
  }
  emit({kind: 'input_end', elapsed_ms: performance.now() - start});
}

async function websocket(c) {
  const ws = new WebSocket(c.url);
  let updated, finish, fail;
  const session = new Promise(resolve => { updated = resolve; });
  const result = new Promise((resolve, reject) => { finish = resolve; fail = reject; });
  // Attach immediately so early close/error events never become unhandled rejections.
  result.catch(() => {});
  ws.addEventListener('message', event => {
    try {
      const item = JSON.parse(event.data);
      emit({kind: 'asr_event', item});
      if (item.type === 'session.updated') updated();
      if (item.type === 'error' || item.type?.endsWith('.failed')) fail(new Error(JSON.stringify(item)));
      if (item.type?.endsWith('input_audio_transcription.completed') && item.transcript?.trim()) finish();
    } catch (error) { fail(error); }
  });
  ws.addEventListener('error', event => fail(new Error(event.message || 'WebSocket error')));
  try {
    await bounded(new Promise((resolve, reject) => {
      ws.addEventListener('open', resolve, {once: true});
      ws.addEventListener('error', reject, {once: true});
    }));
    const settings = c.protocol === 'nemo'
      ? {sample_rate: c.rate, language: 'en-US', endpointing_ms: 10000}
      : {type: 'transcription', audio: {input: {
          format: {type: 'audio/pcm', rate: c.rate}, transcription: {language: 'en'},
          turn_detection: c.automatic ? {type: 'server_vad', threshold: 0.5, prefix_padding_ms: 300, silence_duration_ms: 500} : null
        }}};
    ws.send(JSON.stringify({type: 'session.update', session: settings}));
    await bounded(session, 5000);
    await feed(c, chunk => ws.send(JSON.stringify({type: 'input_audio_buffer.append', audio: chunk.toString('base64')})));
    if (!c.automatic) ws.send(JSON.stringify({type: 'input_audio_buffer.commit'}));
    await bounded(result);
  } finally { ws.close(); }
}

async function chunked(c) {
  let response, rejectResponse;
  const result = new Promise((resolve, reject) => { response = resolve; rejectResponse = reject; });
  result.catch(() => {});
  const request = http.request(c.url, {method: 'POST', headers: {
    'Content-Type': 'application/octet-stream', 'Transfer-Encoding': 'chunked'
  }}, incoming => {
    let pending = '';
    if (incoming.statusCode !== 200) {
      incoming.resume(); rejectResponse(new Error(`HTTP ${incoming.statusCode}`)); return;
    }
    incoming.setEncoding('utf8');
    incoming.on('data', chunk => {
      pending += chunk;
      let split;
      while ((split = pending.indexOf('\n')) >= 0) {
        const line = pending.slice(0, split).trim(); pending = pending.slice(split + 1);
        if (!line.startsWith('data:') || line.slice(5).trim() === '[DONE]') continue;
        try { emit({kind: 'asr_event', item: JSON.parse(line.slice(5))}); }
        catch (error) { rejectResponse(error); }
      }
    });
    incoming.on('end', response); incoming.on('error', rejectResponse);
  });
  request.on('error', rejectResponse);
  try {
    await feed(c, chunk => request.write(chunk));
    request.end();
    await bounded(result);
  } finally { request.destroy(); }
}

emit({kind: 'ready', websocket_available: typeof WebSocket === 'function'});
for await (const line of readline.createInterface({input: process.stdin})) {
  try {
    const c = JSON.parse(line);
    if (c.protocol === 'audio') await chunked(c); else await websocket(c);
    emit({kind: 'complete'});
  } catch (error) { emit({kind: 'failure', error: String(error)}); }
}
