/* Batch WAV comparisons for the standalone audio.cpp test page. */
(() => {
  const voices = document.getElementById('comparison-voices');
  const models = document.getElementById('comparison-models');
  const status = document.getElementById('comparison-status');
  const run = document.getElementById('comparison-run');
  const load = document.getElementById('comparison-load');
  const comparisonText = document.getElementById('comparison-text');
  const allButtons = [document.getElementById('comparison-all-voices'), document.getElementById('comparison-all-models')];
  const urls = new Set();
  const batches = new Set();
  let token = 0;
  let controller;
  let choicesLoaded = false;
  const client = new SpeechClient(PROXY_URL);

  const selected = control => [...control.selectedOptions].map(option => option.value);
  const combinations = (voiceIds, modelIds) => modelIds.flatMap(model => voiceIds.map(voice => ({model, voice})));
  function setStatus(message, state = 'idle') {
    status.textContent = message;
    status.dataset.state = state;
    status.setAttribute('aria-busy', String(state === 'loading'));
  }
  function updateCount() {
    const voiceCount = selected(voices).length;
    const modelCount = selected(models).length;
    const jobs = voiceCount * modelCount;
    run.disabled = !choicesLoaded || !comparisonText.value.trim() || jobs === 0;
    const next = !voiceCount ? 'select a voice' : !modelCount ? 'select a model' : !comparisonText.value.trim() ? 'enter text' : 'ready';
    if (choicesLoaded) setStatus(`${voiceCount} voices × ${modelCount} models = ${jobs} WAVs · ${next}`, jobs ? 'success' : 'idle');
  }
  function populate(control, entries, current, available) {
    const options = entries.map(entry => {
      const option = document.createElement('option');
      option.value = entry.id;
      option.disabled = !entry[available];
      option.textContent = entry.id + (option.disabled ? ' (missing local files)' : '');
      option.selected = !option.disabled && (Array.isArray(current) ? current.includes(entry.id) : entry.id === current);
      return option;
    });
    if (!options.some(option => option.selected)) {
      const firstAvailable = options.find(option => !option.disabled);
      if (firstAvailable) firstAvailable.selected = true;
    }
    control.replaceChildren(...options);
    control.disabled = false;
  }
  async function loadChoices() {
    choicesLoaded = false;
    run.disabled = true;
    load.disabled = true;
    allButtons.forEach(button => { button.disabled = true; });
    voices.disabled = true;
    models.disabled = true;
    setStatus('Loading choices...', 'loading');
    try {
      const response = await fetch(new URL('/proxy/comparison-catalog', PROXY_URL), {cache: 'no-store'});
      if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
      const catalog = await response.json();
      if (!Array.isArray(catalog.voices) || !Array.isArray(catalog.models)) throw new Error('Invalid choices catalog');
      populate(voices, catalog.voices, document.getElementById('voice').value.trim() || activeDefaults?.voice || '', 'available');
      const cloneModels = catalog.models.filter(model => model.clone);
      const requestedModels = cloneModels
        .filter(model => model.installed && /(?:breeze-tts-2|ming3)/i.test(model.id))
        .map(model => model.id);
      populate(models, cloneModels, requestedModels.length ? requestedModels : document.getElementById('model').value.trim() || activeDefaults?.model || '', 'installed');
      choicesLoaded = true;
      allButtons.forEach(button => { button.disabled = false; });
      updateCount();
    } catch (error) {
      voices.replaceChildren();
      models.replaceChildren();
      setStatus(`Choices unavailable: ${error.message}`, 'error');
    } finally { load.disabled = false; }
  }
  load.onclick = loadChoices;
  for (const [id, control] of [['voices', voices], ['models', models]]) {
    control.addEventListener('change', updateCount);
    document.getElementById('comparison-all-' + id).onclick = () => {
      for (const option of control.options) option.selected = !option.disabled;
      updateCount();
    };
  }
  comparisonText.addEventListener('input', updateCount);
  loadChoices();
  function cancel() {
    token++;
    controller?.abort();
    setStatus('Canceled.');
  }
  document.getElementById('comparison-stop').onclick = cancel;
  document.getElementById('comparison-clear').onclick = () => {
    cancel();
    batches.forEach(batch => {
      batch.querySelectorAll('audio').forEach(audio => { audio.pause(); audio.removeAttribute('src'); audio.load(); });
      batch.remove();
    });
    urls.forEach(url => { URL.revokeObjectURL(url); recordings.delete(url); });
    urls.clear(); batches.clear();
    setStatus('WAVs cleared.');
  };
  function createBatch(text, jobs) {
    empty?.remove();
    const batch = document.createElement('section');
    const heading = document.createElement('h2'); heading.textContent = 'Voice / model comparison';
    const input = document.createElement('p'); input.className = 'text'; input.textContent = text;
    const grid = document.createElement('div'); grid.className = 'comparison-results';
    batch.append(heading, input, grid); log.append(batch); batches.add(batch);
    return jobs.map(job => {
      const card = document.createElement('article'); card.className = 'comparison-card';
      const title = document.createElement('h3'); title.textContent = `${job.voice} · ${job.model}`;
      const state = document.createElement('p'); state.className = 'status'; state.textContent = 'Queued';
      card.append(title, state); grid.append(card);
      return {...job, card, state};
    });
  }
  async function generate(job, payload, text) {
    controller = new AbortController(); controllers.add(controller);
    const activeController = controller;
    const started = performance.now(); job.state.textContent = 'Generating...';
    try {
      const response = await client.audioResponse(text, {voice: job.voice}, false, activeController.signal,
        {...payload, model: job.model, voice: job.voice});
      if (!response.ok || response.status === 204) throw new Error(`${response.status}: ${(await response.text()).slice(0, 300) || 'No audio returned'}`);
      const type = response.headers.get('Content-Type') || '';
      if (!/audio\/(wav|wave|x-wav)|application\/octet-stream/i.test(type)) throw new Error(`Expected a complete WAV, received ${type}`);
      const blob = await response.blob();
      if (activeController.signal.aborted) throw new DOMException('Stopped', 'AbortError');
      if (await blob.slice(0, 4).text() !== 'RIFF') throw new Error('Response is not a WAV file');
      const url = URL.createObjectURL(blob); urls.add(url); recordings.add(url);
      const audio = document.createElement('audio'); audio.controls = true; audio.preload = 'metadata'; audio.src = url;
      const download = document.createElement('a'); download.href = url;
      download.download = `${job.model}-${job.voice}.wav`.replace(/[^\w.-]/g, '_'); download.textContent = 'Save WAV';
      job.card.append(audio, download);
      job.state.textContent = `Ready · ${((performance.now() - started) / 1000).toFixed(2)}s · ${(blob.size / 1024).toFixed(0)} KiB`;
    } catch (error) {
      job.state.textContent = error.name === 'AbortError' ? 'Canceled' : `Failed: ${error.message}`;
    } finally { controllers.delete(activeController); controller = undefined; }
  }
  async function execute(jobs, config, text, batchToken, epoch) {
    let finished = 0;
    try {
      for (const job of jobs) {
        if (batchToken !== token || epoch !== generation) break;
        status.textContent = `Generating ${++finished}/${jobs.length}: ${job.voice} · ${job.model}`;
        await generate(job, config, text);
      }
      for (const job of jobs) if (job.state.textContent === 'Queued') job.state.textContent = 'Canceled';
      if (batchToken === token) status.textContent = epoch === generation ? `Done · ${finished} WAVs` : 'Stopped.';
    } finally { run.disabled = false; }
  }
  run.onclick = () => {
    const text = comparisonText.value.trim();
    const jobs = combinations(selected(voices), selected(models));
    if (!text || !jobs.length) { setStatus('Enter text and select a voice and model.', 'error'); return; }
    if (![...document.querySelectorAll('#settings input')].every(input => input.reportValidity())) return;
    let payload;
    try { payload = settings().payload; } catch (error) { status.textContent = error.message; return; }
    const options = {...payload.options};
    for (const key of ['stream_frames_per_event', 'stream_lookahead_margin', 'stream_chunk_policy']) delete options[key];
    payload = {...payload, options, _comparison: true};
    const batchToken = ++token, epoch = generation;
    const cards = createBatch(text, jobs); run.disabled = true;
    status.textContent = `Queued ${jobs.length} WAVs.`;
    pending = pending.then(() => execute(cards, payload, text, batchToken, epoch));
  };
})();
