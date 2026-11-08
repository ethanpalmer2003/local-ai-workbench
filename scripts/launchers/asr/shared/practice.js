// Shared chat behavior for the conversation-only practice route and detailed test route.
const aliases = {audio: 'practice-audio', transcript: 'box', send: 'speak', speak: 'enable-tts'};
const $ = id => document.getElementById(aliases[id] || id);
const query = new URLSearchParams(globalThis.location?.search || '');
const practiceView = document.documentElement?.dataset.view === 'practice';
const testMode = query.get('mode');
const asrOnly = !practiceView && testMode === 'asr';
const llmOnly = !practiceView && testMode === 'llm';
const {checked, wav} = SpeechTools;
const speechClient = new SpeechClient();
for (const id of ['enable-asr', 'enable-llm', 'speak', 'auto-send', 'correct-language', 'assistant-practice-toggle']) SpeechTools.toggle($(id));
const preferencesKey = 'speech-workspace.preferences.v1';
function readPreferences() {
    try {
        const value = JSON.parse(globalThis.localStorage?.getItem(preferencesKey) || '{}');
        return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    } catch (_) { return {}; }
}
let preferences = readPreferences();
function savePreferences() {
    preferences = {...preferences, language: $('language').value || preferences.language,
        assistantMode: $('assistant-practice-toggle').checked ? 'practice' : 'default',
        speechStart: $('speech-start').value,
        level: $('learning-level').value, corrections: $('correct-language').checked,
        autoSend: $('auto-send').checked,
        models: {asr: resolvedAsr()?.id, llm: $('llm-model').value, tts: $('tts-model').value}};
    try { globalThis.localStorage?.setItem(preferencesKey, JSON.stringify(preferences)); } catch (_) {}
}
let capabilities, serviceReady = false, llmModel;
let pendingTtsDefault = null;
$('enable-asr').checked = !llmOnly;
$('enable-llm').checked = !asrOnly;
$('speak').checked = !asrOnly && !llmOnly;
$('auto-send').checked = preferences.autoSend ?? true;
$('correct-language').checked = preferences.corrections ?? true;
$('learning-level').value = ['A1','A2','B1','B2','C1','C2'].includes(preferences.level) ? preferences.level : 'A2';
$('speech-start').value = preferences.speechStart === 'sentence' ? 'sentence' : 'full_reply';
$('assistant-practice-toggle').checked = preferences.assistantMode !== 'default';
function updateAssistantMode() {
    const practice = $('assistant-practice-toggle').checked;
    $('learning-level').disabled = !practice;
    $('correct-language').disabled = !practice;
    $('assistant-mode-help').textContent = practice
        ? 'Adds language and correction guidance.'
        : 'Uses the model default prompt.';
}
updateAssistantMode();
document.title = practiceView ? 'Language practice' : 'Speech workspace';
$('workspace-title').textContent = practiceView ? 'Language practice' : 'Speech workspace';
let measurementHistory = [];
const seconds = milliseconds => `${(milliseconds / 1000).toFixed(3)} s`;
function compactMeasurements() {
    const rows = [];
    for (let index = 0; index < measurementHistory.length;) {
        const current = measurementHistory[index], next = measurementHistory[index + 1];
        const turn = [current, next].find(row => row?.stage === 'Turn including playback');
        const overlap = [current, next].find(row => row?.stage === 'TTS response' && row.result === 'reply pipeline including overlap');
        if (turn && overlap && [current, next].every(row => row?.stage === 'Turn including playback'
            || (row?.stage === 'TTS response' && row.result === 'reply pipeline including overlap'))) {
            const failure = [turn, overlap].find(row => String(row.result).startsWith('failed'));
            rows.push({...turn, result: failure?.result || 'complete · TTS response overlaps this turn'});
            index += 2;
            continue;
        }
        if (next && current.model === next.model
            && new Set([current.stage, next.stage]).size === 2
            && [current.stage, next.stage].includes('LLM request')
            && [current.stage, next.stage].includes('LLM reply')) {
            const server = current.stage === 'LLM request' ? current : next;
            const browser = current.stage === 'LLM reply' ? current : next;
            const failure = [server, browser].find(row => String(row.result).startsWith('failed'));
            rows.push({stage: 'LLM', model: current.model, milliseconds: browser.milliseconds,
                result: failure?.result || `1 request · server ${seconds(server.milliseconds)} · browser ${seconds(browser.milliseconds)}`});
            index += 2;
            continue;
        }
        if (current.stage.endsWith(' request')) {
            let end = index + 1;
            while (end < measurementHistory.length && measurementHistory[end].stage === current.stage
                && measurementHistory[end].model === current.model) end++;
            const group = measurementHistory.slice(index, end);
            if (group.length > 1) {
                const breakdown = group.map(row => seconds(row.milliseconds)).join(' + ');
                const outcomes = [...new Set(group.map(row => row.result))].join(', ');
                rows.push({...current, stage: `${current.stage} ×${group.length}`,
                    milliseconds: group.reduce((total, row) => total + row.milliseconds, 0),
                    result: `${group.length} requests · ${breakdown}${outcomes ? ` · ${outcomes}` : ''}`});
                index = end;
                continue;
            }
        }
        rows.push(current);
        index++;
    }
    return rows;
}
function renderMeasurements() {
    $('measurement-rows').replaceChildren(...compactMeasurements().map(value => {
        const row = document.createElement('tr');
        if (String(value.result).includes('failed')) row.dataset.state = 'failed';
        else if (value.result === 'cancelled') row.dataset.state = 'cancelled';
        for (const text of [value.stage, value.model || 'Not recorded', seconds(value.milliseconds), value.result]) {
            const cell = document.createElement('td'); cell.textContent = text; row.append(cell);
        }
        return row;
    }));
}
function record(stage, milliseconds, result = 'complete', model = 'Not recorded') {
    measurementHistory.unshift({stage, model: model || 'Not recorded', milliseconds, result});
    measurementHistory.length = Math.min(measurementHistory.length, 30);
    renderMeasurements();
}
function modelFor(stage) {
    const role = stage.toLowerCase().split(' ')[0];
    if (role === 'llm') return llmModel || 'Not recorded';
    if (role === 'tts') return modelCatalog?.selected.tts || capabilities?.tts.model || 'Not recorded';
    if (role === 'asr') return modelCatalog?.asr.find(row => row.id === modelCatalog.selected.asr)?.model_id || capabilities?.asr.model || 'Not recorded';
    return ['llm', 'tts'].filter(key => $(key === 'llm' ? 'enable-llm' : 'speak').checked).map(modelFor).join(' → ') || 'No model';
}
function cleanAssistantText(text) {
    return text.replace(/\s+([\p{Pe}\p{Pf},.;:!?...%‰])/gu, '$1');
}
const measured = (stage, operation) => {
    const model = modelFor(stage); // Capture before the request; model changes must not relabel history.
    return SpeechTools.measure(stage, operation, (name, elapsed, result) => record(name, elapsed, result, model));
};
$('clear-metrics').onclick = () => { measurementHistory = []; renderMeasurements(); };
let messages = [], audioContext, microphone, source, recorder, timer, chunks = [], recording = false;
let playbackUrl, turnController, captureEpoch = 0, captureStarting = false;
function buttonLabel(button, label) { button.ariaLabel = label; button.title = label; }
function refreshCaptureButton() {
    const active = recording || captureStarting;
    buttonLabel($('record'), active ? 'Stop microphone' : automatic ? 'Start listening' : 'Record a turn');
    $('record').ariaPressed = String(active);
    $('record').disabled = !active && (busy || replaying || !serviceReady || !$('enable-asr').checked);
    const replay = $('upload-turns');
    if (replay) replay.disabled = replaying || busy || !automatic || !serviceReady || !$('enable-asr').checked;
}
let languageProfiles = {};
let modelCatalog;
function modelOption(label, value, available = true, reason = '') {
    const option = new Option(label + (available ? '' : ' - unavailable'), value);
    option.disabled = !available; option.title = reason; return option;
}
// Explicit Auto policy for the shared Nemotron model; never depend on catalog order.
const nemotronRuntimes = ['audiocpp-nemotron', 'nemo-nemotron', 'parakeetcpp-nemotron-cpu'];
function asrFamily(row) { return nemotronRuntimes.includes(row.id) ? 'nemotron-3.5-streaming-0.6b' : row.id; }
function asrChoices() {
    const row = modelCatalog.asr.find(row => row.id === $('asr-model').value);
    return row ? modelCatalog.asr.filter(item => asrFamily(item) === asrFamily(row))
        .sort((a, b) => (nemotronRuntimes.indexOf(a.id) < 0 ? 100 : nemotronRuntimes.indexOf(a.id))
                     - (nemotronRuntimes.indexOf(b.id) < 0 ? 100 : nemotronRuntimes.indexOf(b.id))) : [];
}
function resolvedAsr() {
    const choices = asrChoices();
    return choices.find(row => row.id === $('asr-framework').value && row.available)
        || choices.find(row => row.available);
}
function fillAsrRuntimes() {
    const choices = asrChoices(), automatic = choices.find(row => row.available);
    const family = choices[0] && asrFamily(choices[0]);
    const preferred = preferences.asrRuntimes?.[family] || 'auto';
    $('asr-framework').replaceChildren(new Option(`Auto${automatic ? ' - ' + automatic.framework : ''}`, 'auto'),
        ...choices.map(row => modelOption(row.framework, row.id, row.available, row.reason)));
    $('asr-framework').value = choices.some(row => row.id === preferred && row.available) ? preferred : 'auto';
    $('asr-framework').title = resolvedAsr()?.model_id || '';
}
function fillAsrModels(preferred) {
    const families = new Map();
    for (const row of modelCatalog.asr) if (!families.has(asrFamily(row))) families.set(asrFamily(row), row);
    const selected = modelCatalog.asr.find(row => row.id === preferred);
    $('asr-model').replaceChildren(...[...families.values()].map(row => modelOption(row.label, row.id,
        modelCatalog.asr.some(item => asrFamily(item) === asrFamily(row) && item.available), row.reason)));
    $('asr-model').value = selected ? families.get(asrFamily(selected)).id : [...families.values()][0]?.id || '';
    fillAsrRuntimes();
}
const catalogCacheKey = 'speech-workspace.catalog.v1';
function renderModelChoices(catalog, verified = true) {
    modelCatalog = catalog;
    const saved = preferences.models || {};
    const selected = modelCatalog.asr.find(row => row.id === saved.asr && row.available)
        || modelCatalog.asr.find(row => row.id === modelCatalog.selected.asr);
    fillAsrModels(selected.id);
    $('tts-model').replaceChildren(...modelCatalog.tts.map(row => modelOption(row.label, row.id, row.available, row.reason)));
    $('tts-model').value = modelCatalog.tts.some(row => row.id === saved.tts && row.available) ? saved.tts : modelCatalog.selected.tts;
    refreshTtsVoices();
    const llms = modelCatalog.llm || [];
    $('llm-model').replaceChildren(...llms.map(row => modelOption(row.label, row.id, row.available, row.reason)));
    $('llm-model').value = llms.some(row => row.id === saved.llm && row.available) ? saved.llm : modelCatalog.selected.llm || '';
    $('llm-model').disabled = !verified || !llms.length;
    for (const id of ['asr-framework', 'asr-model', 'tts-model']) $(id).disabled = !verified;
    showPendingModels();
    if (modelCatalog.error) $('model-status').textContent = `Previous setup restored: ${modelCatalog.error}`;
}
async function loadModelChoices() {
    const response = await fetch('/practice/models', {cache: 'no-store'});
    if (!response.ok) {
        for (const [id, label] of [['asr-model', 'ASR'], ['llm-model', 'LLM']])
            $(id).replaceChildren(new Option(`${label} choices unavailable`, ''));
        if (document.documentElement.dataset.gateway === 'practice')
            $('tts-model').replaceChildren(new Option('TTS choices unavailable', ''));
        $('model-status').textContent = 'Model choices unavailable.';
        return;
    }
    const catalog = await response.json();
    renderModelChoices(catalog);
    try { globalThis.localStorage?.setItem(catalogCacheKey, JSON.stringify(catalog)); } catch (_) {}
}
function restoreModelChoices() {
    try {
        const catalog = JSON.parse(globalThis.localStorage?.getItem(catalogCacheKey) || 'null');
        if (!catalog || !Array.isArray(catalog.asr) || !Array.isArray(catalog.tts)
            || !catalog.asr.some(row => row.id === catalog.selected?.asr)) return;
        renderModelChoices(catalog, false);
        $('model-status').textContent = '';
    } catch (_) {} // Missing, corrupt or blocked storage never prevents a live refresh.
}
function refreshTtsVoices() {
    const choice = modelCatalog?.tts.find(row => row.id === $('tts-model').value);
    if (!choice) return;
    const mode = choice.voice_mode || (choice.family === 'kokoro_tts' ? 'builtin'
        : choice.family === 'breeze_tts' ? 'none' : 'clone');
    let voices = choice.voices;
    if ((!voices || !voices.length) && mode === 'builtin') {
        voices = [...new Set((capabilities?.tts.profiles || []).map(profile => profile.voice))]
            .map(id => ({id, available: true}));
    } else if (!voices && mode === 'clone') {
        voices = [...$('voice').options].filter(option => option.value)
            .map(option => ({id: option.value, available: !option.disabled}));
    }
    const available = (voices || []).filter(voice => voice.available);
    const defaultVoice = choice.default_voice || '';
    const label = mode === 'clone' ? `Default${defaultVoice ? ` (${defaultVoice})` : ''}`
        : mode === 'builtin' ? `Model default${defaultVoice ? ` (${defaultVoice})` : ''}` : 'Model default';
    $('voice').replaceChildren(new Option(label, ''), ...available.map(voice => new Option(voice.id, voice.id)));
    $('voice').value = '';
    $('voice').disabled = mode === 'none' || !available.length;
    $('voice').title = mode === 'none' ? 'This model has no selectable voices' : label;
}
async function applyModels() {
    if (busy) { status('Wait for the reply to finish.'); return; }
    await stopListening(); $('audio').pause();
    const selection = {asr: resolvedAsr()?.id, tts: $('tts-model').value};
    if (modelCatalog?.llm) selection.llm = $('llm-model').value;
    if (!$('speak').checked || !$('enable-asr').checked || !$('enable-llm').checked) {
        try {
            const current = (await (await checked(await fetch('/practice/models'))).json()).selected;
            if (!$('speak').checked) selection.tts = current.tts;
            if (!$('enable-asr').checked) selection.asr = current.asr;
            if ('llm' in selection && !$('enable-llm').checked) selection.llm = current.llm;
        }
        catch (error) { status(error.message); return; }
    }
    setBusy(true);
    for (const id of ['asr-framework', 'asr-model', 'llm-model', 'tts-model', 'record']) $(id).disabled = true;
    try {
        await checked(await fetch('/practice/models', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(selection)}));
        preferences.models = selection;
        await refreshPracticeStatus(); await loadModelChoices();
        savePreferences();
        await globalThis.SpeechDiagnostics?.refresh();
        status(modelCatalog.error ? `Previous setup restored: ${modelCatalog.error}` : 'Choices saved.');
        return !modelCatalog.error;
    } catch (error) { status(error.message); return false; }
    finally {
        setBusy(false);
        for (const id of ['asr-framework', 'asr-model', 'llm-model', 'tts-model']) $(id).disabled = !modelCatalog || (id === 'llm-model' && !modelCatalog.llm?.length);
    }
}
function selectedLanguage() {
    const profile = languageProfiles[$('language').value];
    if (!profile) throw new Error('Choose an available language for the enabled speech stages.');
    return profile;
}
let utteranceStarted;
let automatic = false, replaying = false, session, pendingFrames = [], uploading = false, busy = false, closing;
async function liveRequest(path, body, json = false) {
    return speechClient.live(path, body, json);
}
function handleLiveEvents(events, onDone) {
    for (const event of events) {
        if (event.type === 'transcript.text.delta') $('interim-transcript').textContent += event.delta || '';
        if (event.type === 'transcript.text.snapshot') $('interim-transcript').textContent = event.text || event.transcript || '';
        if (event.type === 'speech_start' && !busy) { utteranceStarted = Date.now(); status('Listening to your turn...'); }
        if (event.type === 'transcript.text.done' && !busy && recording) {
            const text = event.text || event.transcript;
            if (typeof text === 'string' && text.trim()) {
                $('transcript').value = text;
                if (utteranceStarted !== undefined) record('ASR live turn including capture/VAD', Date.now() - utteranceStarted, 'complete', modelFor('asr'));
                utteranceStarted = undefined;
                $('interim-transcript').textContent = '';
                status('Transcript ready.');
                if ($('auto-send').checked && ($('enable-llm').checked || $('speak').checked)) void sendMessage();
            }
            onDone?.();
        }
    }
}
async function flushMicrophone(onDone) {
    if (uploading || !session || !recording || !$('enable-asr').checked) return;
    uploading = true;
    const token = session;
    try {
        const frames = pendingFrames.splice(0), pcm = new ArrayBuffer(frames.length * 1024), view = new DataView(pcm);
        frames.forEach((frame, index) => frame.forEach((sample, i) =>
            view.setInt16(index * 1024 + i * 2, Math.max(-1, Math.min(1, sample)) * 32767, true)));
        const result = await liveRequest(`${token}/audio`, pcm);
        if (token !== session) return;
        handleLiveEvents(result.events, onDone);
    } catch (error) { if (token === session) { await stopListening(); status(error.message); } }
    finally { uploading = false; }
}
async function decodeTo16k(file) {
    const context = new AudioContext();
    try {
        const decoded = await context.decodeAudioData(await file.arrayBuffer());
        const target = new OfflineAudioContext(1, Math.max(1, Math.ceil(decoded.duration * 16000)), 16000);
        const source = target.createBufferSource();
        source.buffer = decoded; source.connect(target.destination); source.start();
        return (await target.startRendering()).getChannelData(0);
    } finally { await context.close(); }
}
async function replayThroughTurns(file) {
    if (busy || recording || replaying) { status('Wait for the current turn to finish.'); return; }
    if (!$('enable-asr').checked || !automatic) return;
    let samples;
    try { samples = await decodeTo16k(file); }
    catch (error) { status(`Could not read that WAV: ${error.message}`); return; }
    let completed = false;
    replaying = true; refreshCaptureButton();
    status('Replaying the WAV through automatic turns...');
    try {
        const result = await liveRequest('start', {language: selectedLanguage().asr_language}, true);
        session = result.session; pendingFrames = []; recording = true;
        const frame = 512, silence = new Float32Array(frame);
        const total = samples.length + 16000 * 2;
        for (let offset = 0; offset < total && !completed; offset += frame) {
            const slice = new Float32Array(frame);
            if (offset < samples.length) slice.set(samples.subarray(offset, Math.min(offset + frame, samples.length)));
            pendingFrames.push(slice);
            if (pendingFrames.length >= 28) {
                await flushMicrophone(() => completed = true);
                await new Promise(resolve => setTimeout(resolve, 16));
            } else await new Promise(resolve => setTimeout(resolve, (frame / 16000) * 1000));
            if (!recording) break;
        }
        for (let index = 0; index < 3 && !completed; index++) {
            pendingFrames.push(silence);
            await flushMicrophone(() => completed = true);
            await new Promise(resolve => setTimeout(resolve, 250));
        }
        if (!completed) status('No completed turn detected in that WAV.');
    } catch (error) { status(error.message); }
    finally {
        if (recording) await stopListening();
        replaying = false; refreshCaptureButton(); globalThis.SpeechLifecycle?.refresh().catch(() => {});
    }
}
async function startListening() {
    const epoch = ++captureEpoch;
    captureStarting = true; refreshCaptureButton();
    try {
        if (!$('enable-asr').checked) return;
        const stream = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true}});
        if (epoch !== captureEpoch) { stream.getTracks().forEach(track => track.stop()); return; }
        microphone = stream;
        audioContext = new AudioContext({sampleRate: 16000});
        if (audioContext.sampleRate !== 16000) throw new Error('This browser cannot capture at 16 kHz. Use a WAV upload.');
        await audioContext.audioWorklet.addModule('/practice-worklet.js');
        source = audioContext.createMediaStreamSource(microphone);
        recorder = new AudioWorkletNode(audioContext, 'practice-microphone');
        status(document.documentElement.dataset.gateway === 'practice'
            ? 'Preparing ASR and microphone...' : 'Starting ASR model if needed...');
        globalThis.SpeechLifecycle?.loading('asr');
        const result = await liveRequest('start', {language: selectedLanguage().asr_language}, true);
        if (epoch !== captureEpoch) { await liveRequest(`${result.session}/stop`, new ArrayBuffer(0)); return; }
        session = result.session; pendingFrames = []; recording = true; captureStarting = false;
        recorder.port.onmessage = event => {
            if (!recording) return;
            if (pendingFrames.length >= 28) { void stopListening().then(() => status('Upload lagged. Restart listening.')); return; }
            pendingFrames.push(busy ? new Float32Array(512) : event.data);
        };
        source.connect(recorder); recorder.connect(audioContext.destination); await audioContext.resume();
        timer = setInterval(flushMicrophone, 128);
        refreshCaptureButton(); $('language').disabled = true; status('Listening. Pause to finish your turn.');
        globalThis.SpeechLifecycle?.refresh().catch(() => {});
    } catch (error) { if (epoch !== captureEpoch) return; await stopListening(); status(error.message); globalThis.SpeechLifecycle?.refresh().catch(() => {}); }
}
async function stopListening() {
    if (closing) return closing;
    captureEpoch++; recording = false; captureStarting = false; clearInterval(timer); utteranceStarted = undefined;
    $('interim-transcript').textContent = '';
    recorder?.disconnect(); source?.disconnect(); microphone?.getTracks().forEach(track => track.stop());
    const token = session; session = undefined; pendingFrames = [];
    closing = (async () => {
        try { if (token) await liveRequest(`${token}/stop`, new ArrayBuffer(0)); }
        finally {
            if (audioContext && audioContext.state !== 'closed') await audioContext.close();
            refreshCaptureButton(); $('language').disabled = false;
        }
    })();
    try { await closing; } finally { closing = undefined; }
}
function status(text) {
    $('status').textContent = text;
    $('status').dataset.state = /^(Starting .* if needed|Transcribing...)/.test(text) ? 'loading' : '';
}
function setBusy(value) {
    busy = value; $('send').disabled = value;
    for (const id of ['enable-asr', 'enable-llm', 'speak', 'upload', 'upload-turns', 'assistant-practice-toggle']) $(id).disabled = value;
    $('load-active-models').disabled = value || !globalThis.SpeechLifecycle?.available();
    $('unload-all').disabled = value || !globalThis.SpeechLifecycle?.available();
    $('learning-level').disabled = value || !$('assistant-practice-toggle').checked;
    $('correct-language').disabled = value || !$('assistant-practice-toggle').checked;
    if (!value) {
        $('enable-asr').disabled = !serviceReady; $('enable-llm').disabled = !chatAvailable;
        refreshLanguages();
    }
    refreshCaptureButton();
}
function cancelTurn() {
    turnController?.abort(); speechClient.stop();
    globalThis.SpeechDiagnostics?.stop(); $('audio').pause();
    globalThis.SpeechLifecycle?.release?.();
    pendingFrames = pendingFrames.map(() => new Float32Array(512));
    status('Cancelling request and playback...');
}
async function transcribe(blob) {
    if (busy) { status('Wait for the request to finish.'); return; }
    setBusy(true); turnController = new AbortController(); globalThis.SpeechLifecycle?.loading('asr');
    status(document.documentElement.dataset.gateway === 'practice' ? 'Transcribing...' : 'Starting ASR model if needed...');
    let complete = false;
    try {
        const value = await measured('ASR upload', () => speechClient.transcribe(blob, selectedLanguage().asr_language, turnController.signal));
        turnController.signal.throwIfAborted();
        if (typeof value.text !== 'string' || !value.text.trim()) throw new Error('No speech recognized. Try a clearer recording.');
        $('transcript').value = value.text; status('Transcript ready.'); complete = true;
    } catch (error) { status(error.name === 'AbortError' ? 'Transcription cancelled.' : error.message); }
    finally { setBusy(false); globalThis.SpeechLifecycle?.refresh().catch(() => {}); }
    if (complete && $('auto-send').checked && ($('enable-llm').checked || $('speak').checked)) await sendMessage();
}
async function stopRecording() {
    if (!recording) return;
    recording = false; clearTimeout(timer); recorder.disconnect(); source.disconnect();
    microphone.getTracks().forEach(track => track.stop());
    const rate = audioContext.sampleRate;
    await audioContext.close();
    const samples = new Float32Array(chunks.reduce((n, chunk) => n + chunk.length, 0));
    let offset = 0; chunks.forEach(chunk => {samples.set(chunk, offset); offset += chunk.length;});
    captureStarting = false; refreshCaptureButton();
    await transcribe(wav(samples, rate));
}
$('record').onclick = async () => {
    if (recording || captureStarting) {
        if (automatic || !recording) await stopListening();
        else await stopRecording();
        status('Microphone stopped.'); return;
    }
    if (!$('enable-asr').checked || busy) return;
    if (pendingModels() && !await applyModels()) return;
    if (busy) return;
    if (automatic) { await startListening(); return; }
    const epoch = ++captureEpoch;
    captureStarting = true; refreshCaptureButton();
    try {
        const stream = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1}});
        if (epoch !== captureEpoch) { stream.getTracks().forEach(track => track.stop()); return; }
        microphone = stream;
        audioContext = new AudioContext({sampleRate: 16000});
        source = audioContext.createMediaStreamSource(microphone);
        recorder = audioContext.createScriptProcessor(4096, 1, 1); chunks = [];
        recorder.onaudioprocess = event => {if (recording) chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));};
        source.connect(recorder); recorder.connect(audioContext.destination); recording = true; captureStarting = false;
        refreshCaptureButton(); status('Recording...');
        timer = setTimeout(stopRecording, 29500);
    } catch (error) { if (epoch === captureEpoch) { await stopListening(); status(error.message); } }
};

$('upload').onchange = () => {if ($('enable-asr').checked && $('upload').files[0]) transcribe($('upload').files[0]);};
$('upload-turns').onchange = () => {
    const file = $('upload-turns').files?.[0];
    if (file) void replayThroughTurns(file);
    $('upload-turns').value = '';
};
async function replyTo(text, onText) {
    const language = selectedLanguage().label;
    const next = [...messages, {role: 'user', content: text}];
    let partial = '', pendingSpeechWhitespace = '';
    const prompt = $('assistant-practice-toggle').checked
        ? [{role: 'system', content: `Help me practise conversation in ${language === 'Detect automatically' ? 'the language I use' : language}. Use CEFR ${$('learning-level').value || 'A2'} vocabulary and grammar. Keep replies to one or two short sentences and ask one follow-up question. ${$('correct-language').checked ? 'Offer at most one brief correction when useful.' : 'Do not correct my language unless I ask.'}`}]
        : [];
    const reply = await measured('LLM reply', () => speechClient.chat({
            messages: [...prompt, ...next],
            max_tokens: 256, temperature: 0.5, stream: true,
            reasoning_effort: 'none', chat_template_kwargs: {enable_thinking: false}
    }, turnController.signal, delta => {
        if (!partial && document.documentElement.dataset.gateway !== 'practice') {
            status($('speak').checked ? 'LLM ready · preparing speech...' : 'LLM ready · generating reply...');
        }
        partial += delta;
        $('history').textContent = [...next, {role: 'assistant', content: cleanAssistantText(partial)}]
            .map(message => `${message.role === 'user' ? 'You' : 'Tutor'}: ${message.content}`).join('\n\n');
        const combined = pendingSpeechWhitespace + delta;
        const trailingWhitespace = combined.match(/\s+$/u)?.[0] || '';
        const ready = trailingWhitespace ? combined.slice(0, -trailingWhitespace.length) : combined;
        pendingSpeechWhitespace = trailingWhitespace;
        onText?.(cleanAssistantText(ready));
    }));
    turnController.signal.throwIfAborted();
    if (typeof reply !== 'string' || !reply.trim()) throw new Error('The model returned no text.');
    const cleanedReply = cleanAssistantText(reply).trimEnd();
    messages = [...next, {role: 'assistant', content: cleanedReply}];
    $('history').textContent = messages.map(message => `${message.role === 'user' ? 'You' : 'Tutor'}: ${message.content}`).join('\n\n');
    return cleanedReply;
}
function speechOptions() {
    const options = globalThis.SpeechDiagnostics?.requestSettings?.() || {};
    return {...options, audio: $('audio'), onMode: mode => status(`TTS ready · ${mode} playback`)};
}
async function speakText(text) {
    await measured('TTS response', () => speechClient.say(text, selectedLanguage(), turnController.signal, speechOptions()));
}
async function sendMessage() {
    if (busy) return;
    if (pendingModels() && !await applyModels()) return;
    if (busy) return;
    const text = $('transcript').value.trim(); if (!text) return;
    setBusy(true); turnController = new AbortController();
    if ($('enable-llm').checked) globalThis.SpeechLifecycle?.loading('llm');
    if ($('speak').checked) globalThis.SpeechLifecycle?.loading('tts');
    pendingFrames = pendingFrames.map(() => new Float32Array(512));
    try {
        if ($('speak').checked && speechClient.policy?.tts?.mode === 'streaming') await speechClient.prepare();
        await measured('Turn including playback', async () => {
            if (document.documentElement.dataset.gateway === 'practice') {
                status($('enable-llm').checked ? 'Thinking...' : 'Processing text...');
            } else if ($('enable-llm').checked) {
                status('Starting LLM model if needed...');
            } else if ($('speak').checked) {
                status('Starting TTS model if needed...');
            } else {
                status('Processing text...');
            }
            const spoken = $('enable-llm').checked && $('speak').checked
                ? speechClient.utterance(selectedLanguage(), turnController.signal,
                    {...speechOptions(), textMode: $('speech-start').value}) : null;
            const speechStarted = globalThis.performance?.now() ?? Date.now();
            const output = $('enable-llm').checked ? await replyTo(text, delta => spoken?.feed(delta)) : text;
            turnController.signal.throwIfAborted();
            if (spoken) {
                await spoken.finish();
                record('TTS response', (globalThis.performance?.now() ?? Date.now()) - speechStarted, 'reply pipeline including overlap', modelFor('tts'));
            } else if ($('speak').checked) await speakText(output);
            turnController.signal.throwIfAborted();
        });
        status(recording ? 'Listening. Pause to finish your next turn.' : 'Ready.');
    } catch (error) { turnController?.abort(); speechClient.stop(); status(error.name === 'AbortError' ? 'Response cancelled.' : error.message); }
    finally { setBusy(false); globalThis.SpeechLifecycle?.refresh().catch(() => {}); }
}
// The diagnostic form and keyboard use this controller; fixtures can invoke the same action directly.
globalThis.SpeechWorkspace = {run: sendMessage, record, cancel: cancelTurn, busy: () => busy, modelFor};
if (!globalThis.SpeechDiagnostics) $('send').onclick = sendMessage;
$('clear').onclick = async () => {
    cancelTurn(); await stopListening(); messages = [];
    $('history').textContent = '';
    $('transcript').value = ''; $('audio').hidden = true; $('audio').src = '';
    status('Conversation cleared.');
};
$('save-conversation').onclick = () => {
    const data = {saved_at: new Date().toISOString(), assistant_mode: $('assistant-practice-toggle').checked ? 'practice' : 'default', language: $('language').value,
                  level: $('learning-level').value, models: modelCatalog?.selected, messages};
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = `language-practice-${Date.now()}.json`;
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
};
let chatAvailable = false;
function refreshLanguages() {
    if (!capabilities) return;
    const previous = preferences.language || $('language').value;
    const selectedTts = modelCatalog?.tts.find(row => row.id === $('tts-model').value);
    const defaultCode = pendingTtsDefault || selectedTts?.default_language || capabilities.tts.default_language;
    const names = Object.fromEntries([...capabilities.asr.languages, ...capabilities.tts.languages].map(row => [row.code, row.name]));
    const recognition = [{code: 'auto', locale: 'auto', label: 'Detect automatically', asr_language: 'auto'},
        ...capabilities.asr.languages.filter(row => !capabilities.asr.ready_languages || capabilities.asr.ready_languages.includes(row.code))
            .map(row => ({code: row.code, locale: row.code, label: row.name, asr_language: row.code}))];
    const voices = capabilities.tts.profiles?.map(profile => ({...profile, label: names[profile.code] || profile.code, asr_language: 'auto'})) || capabilities.common;
    const profiles = $('speak').checked ? ($('enable-asr').checked ? capabilities.common : voices) : recognition;
    const usable = profiles.filter(profile => profile.available !== false);
    languageProfiles = Object.fromEntries(usable.map(profile => [profile.locale, profile]));
    $('language').replaceChildren(...profiles.map(profile => modelOption(profile.label, profile.locale, profile.available !== false, profile.unavailable_reason)));
    const modelDefault = usable.find(profile => profile.code === defaultCode || profile.locale === defaultCode);
    const selected = pendingTtsDefault
        ? modelDefault?.locale || (languageProfiles[previous] ? previous : usable[0]?.locale || '')
        : languageProfiles[previous] ? previous : modelDefault?.locale || usable[0]?.locale || '';
    $('language').value = selected;
    if (pendingTtsDefault && modelDefault) pendingTtsDefault = null;
    $('language').disabled = !usable.length || recording;
    refreshCaptureButton();
    $('upload').disabled = !$('enable-asr').checked || !serviceReady;
    $('upload-turns').disabled = !automatic || !$('enable-asr').checked || !serviceReady;
    buttonLabel($('send'), $('enable-llm').checked ? 'Send' : $('speak').checked ? 'Speak text' : 'Keep transcript');
}
async function stagesChanged(id) {
    if (!$('enable-asr').checked && recording) await stopListening();
    refreshLanguages();
    if (!$(id).checked) {
        const stage = {'enable-asr': 'asr', 'enable-llm': 'llm', speak: 'tts'}[id];
        try {
            await globalThis.SpeechLifecycle?.action(stage, 'unload');
            status(`${stage.toUpperCase()} unloaded.`);
        }
        catch (error) { $(id).checked = true; refreshLanguages(); status(error.message); }
    } else status(`${({'enable-asr': 'ASR', 'enable-llm': 'LLM', speak: 'TTS'})[id]} enabled; loads on request.`);
}
for (const id of ['enable-asr', 'enable-llm', 'speak']) $(id).onchange = () => stagesChanged(id);
function activeStages() {
    return [['asr', 'enable-asr'], ['llm', 'enable-llm'], ['tts', 'speak']]
        .filter(([, toggle]) => $(toggle).checked).map(([stage]) => stage);
}
$('load-active-models').onclick = async () => {
    if (busy) { status('Wait for request to finish.'); return; }
    const stages = activeStages();
    if (!stages.length) { status('No active stages.'); return; }
    for (const stage of stages) globalThis.SpeechLifecycle?.loading(stage, 'preload', true);
    if (pendingModels() && !await applyModels()) {
        await globalThis.SpeechLifecycle?.refresh().catch(() => {});
        return;
    }
    setBusy(true);
    try {
        await stopListening();
        for (const stage of stages) await globalThis.SpeechLifecycle.action(stage, 'load', 'preload');
        status('Active models loaded.');
    } catch (error) { status(error.message); }
    finally { setBusy(false); globalThis.SpeechLifecycle?.refresh().catch(() => {}); }
};
$('unload-all').onclick = async () => {
    if (busy) { status('Wait for request to finish.'); return; }
    setBusy(true);
    try {
        await stopListening();
        await globalThis.SpeechLifecycle?.action('all', 'unload');
        for (const id of ['enable-asr', 'enable-llm', 'speak']) $(id).checked = false;
        refreshLanguages(); status('All models unloaded.');
    } catch (error) { status(error.message); }
    finally { setBusy(false); globalThis.SpeechLifecycle?.refresh().catch(() => {}); }
};
async function refreshPracticeStatus() {
    const response = await checked(await fetch('/asr/status')), value = await response.json();
    llmModel = value.llm_model;
    speechClient.policy = value.delivery || null;
    if (value.delivery) renderDelivery(value.delivery);
    $('llm-runtime').textContent = value.chat_runtime === 'none' ? 'No chat runtime' : `${value.chat_runtime} · current model`;
    chatAvailable = value.chat_runtime !== 'none'; $('enable-llm').disabled = !chatAvailable;
    if (!chatAvailable) $('enable-llm').checked = false;
    serviceReady = value.ready; automatic = value.automatic_turns; capabilities = value.languages;
    workspacePid = value.workspace_pid || workspacePid;
    if (!capabilities) throw new Error('Language capabilities unavailable. Restart the service.');
    refreshTtsVoices();
    $('enable-asr').disabled = !serviceReady;
    refreshLanguages();
    $('asr-languages').textContent = `ASR: ${capabilities.asr.model}: ${capabilities.asr.languages.map(row => row.name).join(', ') || 'Coverage unknown'}.`;
    $('tts-languages').textContent = `TTS: ${capabilities.tts.model}: ${capabilities.tts.languages.map(row => row.name).join(', ')}.`;
    $('language-notes').textContent = [capabilities.asr.notes, capabilities.tts.notes].filter(Boolean).join(' ');
    refreshCaptureButton();
}
let workspacePid;
const restartButton = $('restart-workspace');
if (restartButton) restartButton.onclick = async () => {
    restartButton.disabled = true;
    const status = $('restart-workspace-status');
    status.textContent = 'Restarting...';
    try {
        const beforeResponse = await checked(await fetch('/asr/status', {cache: 'no-store'}));
        const before = await beforeResponse.json();
        workspacePid = before.workspace_pid || workspacePid;
        await checked(await fetch('/workspace/restart', {method: 'POST'}));
        const deadline = Date.now() + 60000;
        while (Date.now() < deadline) {
            await new Promise(resolve => setTimeout(resolve, 350));
            try {
                const response = await fetch('/asr/status', {cache: 'no-store'});
                if (!response.ok) continue;
                const current = await response.json();
                if (current.workspace_pid && current.workspace_pid !== before.workspace_pid) {
                    status.textContent = 'Restarted';
                    location.reload();
                    return;
                }
            } catch (_) { /* Wait for the replacement service. */ }
        }
        throw new Error('Workspace did not return within 60 seconds');
    } catch (error) {
        status.textContent = `Restart failed: ${error.message}`;
        restartButton.disabled = false;
    }
};
function pendingModels() {
    return modelCatalog && ['asr', 'tts', 'llm'].some(kind => {
        const control = kind === 'llm' ? 'enable-llm' : kind === 'tts' ? 'speak' : 'enable-asr';
        return $(control).checked && modelCatalog.selected[kind] && (kind === 'asr' ? resolvedAsr()?.id : $(`${kind}-model`).value) !== modelCatalog.selected[kind];
    });
}
function showPendingModels() {
    $('model-status').textContent = pendingModels() ? 'Pending · applies on Send or Load all active' : '';
}
$('asr-framework').onchange = () => {
    const family = asrChoices()[0];
    preferences.asrRuntimes = {...preferences.asrRuntimes, [asrFamily(family)]: $('asr-framework').value};
    $('asr-framework').title = resolvedAsr()?.model_id || '';
    showPendingModels(); savePreferences();
};
$('asr-model').onchange = () => { fillAsrRuntimes(); showPendingModels(); savePreferences(); };
for (const id of ['llm-model', 'tts-model']) $(id).onchange = () => { showPendingModels(); savePreferences(); };
$('tts-model').onchange = () => {
    pendingTtsDefault = modelCatalog?.tts.find(row => row.id === $('tts-model').value)?.default_language || 'en';
    showPendingModels(); savePreferences();
    if (document.documentElement.dataset.gateway === 'practice') { refreshTtsVoices(); refreshLanguages(); }
    else globalThis.loadModelDefaults?.();
};
for (const id of ['language', 'learning-level', 'correct-language', 'auto-send', 'speech-start']) $(id).onchange = savePreferences;
$('assistant-practice-toggle').onchange = () => { updateAssistantMode(); savePreferences(); };
function renderDelivery(plan) {
    for (const stage of ['asr', 'llm', 'tts']) {
        const control = $(`delivery-${stage}`);
        if (!control) continue;
        control.replaceChildren(new Option(`Auto - ${plan[stage].mode}`, 'auto'),
            ...['streaming', 'chunked', 'whole'].map(mode => modelOption(mode === 'whole' ? 'Whole request' : mode,
                mode, plan[stage].supported.includes(mode), 'Unsupported by this runtime')));
        control.value = plan[stage].requested; control.disabled = false;
    }
}
for (const stage of ['asr', 'llm', 'tts']) {
    const control = $(`delivery-${stage}`);
    if (!control) continue;
    control.onchange = async () => {
        if (busy) { renderDelivery(speechClient.policy); return; }
        await stopListening();
        try {
            const plan = await speechClient.json('/workspace/delivery', {stage,
                model: speechClient.policy[stage].model, mode: control.value});
            speechClient.policy = plan; renderDelivery(plan); await refreshPracticeStatus();
            await globalThis.SpeechDiagnostics?.refresh();
        } catch (error) { status(error.message); if (speechClient.policy) renderDelivery(speechClient.policy); }
    };
}
restoreModelChoices();
refreshPracticeStatus().then(loadModelChoices).catch(error => {
    serviceReady = false; chatAvailable = false;
    for (const id of ['enable-asr', 'enable-llm']) { $(id).checked = false; $(id).disabled = true; }
    for (const [id, label] of [['asr-model', 'ASR'], ['llm-model', 'LLM']])
        $(id).replaceChildren(new Option(`${label} choices unavailable`, ''));
    $('record').disabled = true; $('upload').disabled = true; $('upload-turns').disabled = true;
    $('llm-runtime').textContent = 'Open practice launcher for ASR/chat';
    languageProfiles = {auto: {locale: 'auto', label: 'Detect automatically'}};
    $('language').replaceChildren(new Option('Model default', 'auto')); $('language').value = 'auto';
    buttonLabel($('send'), 'Speak text');
    status('TTS available; ASR/chat need practice service.');
});
window.addEventListener('pagehide', () => {
    if (session) navigator.sendBeacon(`/asr/live/${session}/stop`, new Blob([]));
    microphone?.getTracks().forEach(track => track.stop());
    if (playbackUrl) URL.revokeObjectURL(playbackUrl);
});
