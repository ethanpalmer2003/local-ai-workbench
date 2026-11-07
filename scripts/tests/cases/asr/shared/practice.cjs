// Browser contract with simulated capture/network; no device or native model access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const practiceOnly = process.argv.includes('--practice');
const cached = process.argv.includes('--cached');
const stored = new Map(cached ? [['speech-workspace.preferences.v1', JSON.stringify({language:'ja', level:'B2', corrections:false, autoSend:false, models:{llm:'llamacpp/alternate'}})]] : []);
const asrOnly = !practiceOnly && process.argv.includes('--asr');
const root = path.resolve(__dirname, '../../../../launchers/asr/shared');
let Processor, frames = [];
vm.runInNewContext(fs.readFileSync(path.join(root, 'practice-worklet.js'), 'utf8'), {
    AudioWorkletProcessor: class { constructor() { this.port = {postMessage: frame => frames.push(frame)}; } },
    registerProcessor: (_, cls) => Processor = cls
});
const processor = new Processor();
for (let i = 0; i < 4; i++) processor.process([[new Float32Array(128).fill(.2)]]);
assert.equal(frames.length, 1); assert.equal(frames[0].length, 512);
const elements = {}, requests = [], listeners = {};
for (const id of ['model-status', 'asr-framework', 'asr-model', 'llm-model', 'tts-model']) elements[id] = {value: '', textContent: '', disabled: false, replaceChildren(...options) {this.options = options;}};
for (const id of ['record', 'stop', 'language', 'status', 'transcript', 'send', 'speak', 'history', 'audio', 'upload', 'upload-turns', 'clear', 'runtime', 'instructions', 'asr-languages', 'tts-languages', 'language-notes']) elements[id] = {value: '', textContent: '', disabled: false, dataset: {}};
for (const id of ['speech-start']) elements[id] = {value: 'full_reply', textContent: '', disabled: false};
elements.voice = {value: '', disabled: false, title: '', options: [], replaceChildren(...options) { this.options = options; }};
elements.language.replaceChildren = (...options) => { elements.language.options = options; };
elements.language.value = 'fr'; elements.language.selectedOptions = [{textContent: 'French'}]; elements.speak.checked = true;
Object.assign(elements.audio, {
    addEventListener: (name, callback) => listeners[name] = callback,
    removeEventListener: name => delete listeners[name],
    play: async () => setImmediate(() => listeners.ended?.()), pause: () => listeners.pause?.()
});
let node, stopped = false, finalSent = false;
let selectedModels = {asr: 'audiocpp-nemotron', tts: 'kokoro', llm: 'llamacpp/gemma'};
for (const id of ['tts-choice', 'conversation-actions', 'conversation-history', 'test-link', 'chat-link']) elements[id] = {};
for (const id of ['enable-asr', 'enable-llm', 'measurements', 'measurement-rows', 'clear-metrics', 'workspace-title', 'conversation-title', 'llm-runtime']) elements[id] = {children: [], append(...rows) {this.children.push(...rows);}, prepend(...rows) {this.children.unshift(...rows);}, replaceChildren(...rows) {this.children = rows;}};
Object.assign(elements, {'enable-tts': elements.speak, 'speak': elements.send, 'capture-stop': elements.stop, 'practice-audio': elements.audio, 'box': elements.transcript});
for (const id of ['load-active-models', 'unload-all']) elements[id] = {};
for (const id of ['learning-level', 'correct-language', 'auto-send', 'assistant-practice-toggle', 'assistant-mode-help', 'interim-transcript', 'save-conversation', 'lifecycle-note', 'lifecycle-log', 'residency-asr', 'residency-llm', 'residency-tts']) elements[id] = {value: '', textContent: '', hidden: false, dataset: {}};
const body = {dataset: {}};
const documentElement = {dataset: {}};
const context = vm.createContext({
    localStorage: {getItem: key => stored.get(key), setItem: (key, value) => stored.set(key, value)},
    AbortController, URLSearchParams, location: {pathname: practiceOnly ? '/practice' : '/test/', search: (asrOnly || practiceOnly) ? '?mode=asr' : ''},
    Option: class { constructor(text, value) { this.textContent = text; this.value = value; } },
    document: {body, documentElement, getElementById: id => elements[id], querySelector: () => ({}), createElement: () => ({children: [], dataset: {}, append(...rows) {this.children.push(...rows);}})},
    navigator: {mediaDevices: {getUserMedia: async () => ({getTracks: () => [{stop: () => stopped = true}]})}},
    AudioContext: class {
        constructor() { this.sampleRate = 16000; this.state = 'running'; this.audioWorklet = {addModule: async () => {}}; }
        async decodeAudioData() { return {duration: 0, numberOfChannels: 1}; }
        createMediaStreamSource() { return {connect() {}, disconnect() {}}; }
        async resume() {} async close() { this.state = 'closed'; }
    },
    OfflineAudioContext: class {
        constructor(_channels, length) { this.length = length; }
        createBufferSource() { return {buffer: null, connect() {}, start() {}}; }
        async startRendering() { return {getChannelData: () => new Float32Array(this.length)}; }
    },
    AudioWorkletNode: class { constructor() { this.port = {}; node = this; } connect() {} disconnect() {} },
    fetch: async (url, options = {}) => {
        requests.push([url, options]);
        let value;
        if (url === '/practice/models') {
            if (options.method === 'POST') selectedModels = JSON.parse(options.body);
            value = {asr: [{id: 'audiocpp-nemotron', framework: 'AudioCpp', label: 'Nemotron', available: true},
                {id: 'nemo-nemotron', framework: 'NeMo-Speech.cpp', label: 'Nemotron', available: true},
                {id: 'parakeetcpp-nemotron-cpu', framework: 'parakeet.cpp CPU', label: 'Nemotron', available: false}],
            llm: [{id: 'llamacpp/gemma', label: 'Gemma', available: true}, {id: 'llamacpp/alternate', label: 'Alternate', available: true}],
            tts: [{id: 'kokoro', label: 'Kokoro', available: true}, {id: 'compact', label: 'Compact', available: true}], selected: selectedModels};
        }
        else if (url === '/workspace/lifecycle') value = {log: 'fixture.jsonl', stages: {
            asr: {state: 'unloaded'}, llm: {state: 'unloaded'}, tts: {state: 'unloaded'}}, events: []};
        else if (url === '/asr/status') value = {ready: true, automatic_turns: true, engine: 'audiocpp-nemotron', chat_runtime: 'test', llm_model: 'gemma-e4b-q4.gguf', languages: {
            asr: {model: 'ASR', languages: [{code: 'fr', name: 'French'}, {code: 'ja', name: 'Japanese'}, {code: 'th', name: 'Thai'}], notes: ''},
            tts: {model: 'Kokoro', languages: [{code: 'fr', name: 'French'}, {code: 'ja', name: 'Japanese'}, {code: 'th', name: 'Thai'}], notes: ''},
            common: [{code: 'fr', locale: 'fr-fr', label: 'French', voice: 'ff_siwis', asr_language: 'fr'},
                     {code: 'ja', locale: 'ja', label: 'Japanese', voice: 'jf_alpha', asr_language: 'ja'}]}};
        else if (url.endsWith('/start')) value = {session: 'token'};
        else if (url.endsWith('/audio')) {
            assert.equal(options.body.byteLength % 1024, 0);
            value = {events: finalSent ? [] : [{type: 'transcript.text.done', text: 'Bonjour'}]}; finalSent = true;
        } else if (url === '/v1/chat/completions') value = {choices: [{message: {content: 'Salut !'}}]};
        else value = {events: []};
        return {ok: true, json: async () => value, blob: async () => new Blob(['wave'])};
    },
    URL: {createObjectURL: () => 'blob:test', revokeObjectURL() {}}, Blob, FormData,
    window: {addEventListener() {}}, setInterval: () => 1, clearInterval() {}, setTimeout, clearTimeout,
    console, Float32Array, ArrayBuffer, DataView
});
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
    const shared = path.resolve(root, '../../shared/browser');
    for (const name of ['pcm_audio.js', 'speech_tools.js', 'speech_client.js']) vm.runInContext(fs.readFileSync(path.join(shared, name), 'utf8'), context);
    const html = fs.readFileSync(path.resolve(root, '../../../tests/ui/speech.html'), 'utf8');
    const presentation = html.match(/<script>([\s\S]*?)<\/script>/)[1];
    vm.runInContext(presentation, context);
    assert.equal(documentElement.dataset.view, practiceOnly ? 'practice' : 'test');
    vm.runInContext(fs.readFileSync(path.join(root, 'practice.js'), 'utf8'), context);
    assert.equal(context.document.title, practiceOnly ? 'Language practice' : 'Speech workspace');
    if (practiceOnly) {
        assert.equal(elements['enable-llm'].checked, true);
        assert.equal(elements['enable-tts'].checked, true);
        assert.equal(elements['workspace-title'].textContent, 'Language practice');
    }
    vm.runInContext(fs.readFileSync(path.join(shared, 'workspace_lifecycle.js'), 'utf8'), context);
    if (cached) {
        await tick(); await tick();
        assert.equal(elements.language.value, 'ja');
        assert.equal(elements['learning-level'].value, 'B2');
        assert.equal(elements['auto-send'].checked, false);
        assert.equal(elements['correct-language'].checked, false);
        assert.equal(elements['llm-model'].value, 'llamacpp/alternate');
        vm.runInContext("preferences = {}; $('learning-level').value = 'A2'; $('auto-send').checked = true; $('correct-language').checked = true;", context);
        await vm.runInContext('loadModelChoices()', context);
    }
    await tick(); await tick();
    const savedCatalog = stored.get('speech-workspace.catalog.v1');
    assert.ok(savedCatalog, 'Verified option lists must be cached');
    elements['llm-model'].value = '';
    vm.runInContext('restoreModelChoices()', context);
    assert.ok(elements['llm-model'].value, 'Cached choices render synchronously');
    assert.equal(elements['asr-model'].disabled, true, 'Cached availability must be verified before applying');
    await vm.runInContext('loadModelChoices()', context);
    assert.equal(elements['asr-model'].options.length, 1, 'One model across runtime conversions');
    assert.equal(elements['asr-framework'].value, 'auto');
    assert.equal(vm.runInContext('resolvedAsr().id', context), 'audiocpp-nemotron');
    elements['asr-framework'].value = 'nemo-nemotron'; elements['asr-framework'].onchange();
    assert.equal(vm.runInContext('resolvedAsr().id', context), 'nemo-nemotron');
    await vm.runInContext('loadModelChoices()', context);
    assert.equal(elements['asr-framework'].value, 'nemo-nemotron', 'Manual override survives refresh');
    await vm.runInContext('applyModels()', context);
    assert.equal(selectedModels.asr, 'nemo-nemotron', 'Apply sends the resolved runtime profile');
    vm.runInContext("modelCatalog.asr.find(row => row.id === 'nemo-nemotron').available = false; fillAsrRuntimes()", context);
    assert.equal(elements['asr-framework'].value, 'auto', 'Unavailable override falls back to Auto');
    elements['asr-framework'].onchange();
    await vm.runInContext('applyModels()', context);
    assert.equal(selectedModels.asr, 'audiocpp-nemotron');
    await vm.runInContext('loadModelChoices()', context);
    const correction = elements['correct-language'];
    assert.equal(correction.ariaPressed, 'true');
    correction.onclick(); assert.equal(correction.checked, false); assert.equal(correction.ariaPressed, 'false');
    assert.equal(JSON.parse(stored.get('speech-workspace.preferences.v1')).corrections, false);
    correction.onclick(); assert.equal(correction.checked, true);
    correction.disabled = true; correction.onclick(); assert.equal(correction.checked, true); correction.disabled = false;
    const wave = await vm.runInContext('wav(new Float32Array([0, 1, -1]), 16000).arrayBuffer()', context);
    assert.equal(Buffer.from(wave).toString('ascii', 0, 4), 'RIFF');
    assert.equal(new DataView(wave).getInt16(46, true), 32767);
    vm.runInContext("record('older', 1); record('newer', 2)", context);
    assert.equal(elements['measurement-rows'].children[0].children[0].textContent, 'newer');
    elements['measurement-rows'].replaceChildren();
    await tick(); elements['enable-llm'].checked = !asrOnly; elements.language.value = asrOnly ? 'fr' : 'fr-fr'; await elements.record.onclick();
    assert.equal(elements.record.ariaLabel, 'Stop microphone');
    assert.equal(elements.record.disabled, false);
    for (let i = 0; i < 4; i++) node.port.onmessage({data: new Float32Array(512)});
    await vm.runInContext('flushMicrophone()', context); await tick(); await tick();
    if (asrOnly) {
        assert.equal(elements.transcript.value, 'Bonjour');
        await elements.send.onclick();
        assert.ok(!requests.some(([url]) => ['/v1/chat/completions', '/v1/audio/speech'].includes(url)));
        assert.equal(elements['enable-llm'].checked, false);
        assert.equal(elements['enable-tts'].checked, false);
        assert.ok(elements.language.options.some(row => row.value === 'th'));
        await elements.record.onclick(); assert.ok(stopped);
        selectedModels.tts = 'compact'; // Another practice tab changed TTS after this panel loaded.
        await vm.runInContext('applyModels()', context);
        assert.equal(selectedModels.tts, 'compact');
        console.log('[OK] ASR-only mode recognizes speech without chat/TTS, including languages outside TTS coverage');
        return;
    }
    assert.match(elements.history.textContent, /You: Bonjour/);
    assert.match(elements.history.textContent, /Tutor: Salut/);
    assert.match(elements.history.textContent, /Tutor: Salut!/);
    assert.doesNotMatch(elements.history.textContent, /Salut\s+!/);
    const llmMeasurement = elements['measurement-rows'].children.find(row => row.children[0].textContent === 'LLM reply');
    assert.equal(llmMeasurement.children[1].textContent, 'gemma-e4b-q4.gguf');
    const overlappedTurn = elements['measurement-rows'].children.find(row => row.children[0].textContent === 'Turn including playback');
    assert.match(overlappedTurn.children[1].textContent, /kokoro$/);
    const speech = requests.find(([url]) => url === '/v1/audio/speech');
    assert.equal(JSON.parse(speech[1].body).voice, 'ff_siwis');
    assert.equal(JSON.parse(speech[1].body).options.language, 'fr-fr');
    const prompt = JSON.parse(requests.find(([url]) => url === '/v1/chat/completions')[1].body).messages[0].content;
    assert.match(prompt, /CEFR A2/); assert.match(prompt, /one brief correction/);
    assert.match(elements['asr-languages'].textContent, /Japanese/);
    assert.equal(elements.language.options.length, 2);
    await elements.record.onclick(); assert.ok(stopped);
    assert.ok(requests.some(([url]) => url === '/asr/live/token/stop'));
    elements['auto-send'].checked = false; finalSent = false;
    const beforeReview = requests.filter(([url]) => url === '/v1/chat/completions').length;
    await elements.record.onclick(); node.port.onmessage({data: new Float32Array(512)});
    await vm.runInContext('flushMicrophone()', context); await tick();
    assert.equal(elements.transcript.value, 'Bonjour');
    assert.equal(requests.filter(([url]) => url === '/v1/chat/completions').length, beforeReview);
    await elements.record.onclick(); elements['auto-send'].checked = true;

    elements.language.value = 'ja'; elements.transcript.value = 'Hello'; await elements.send.onclick();
    const japanese = requests.filter(([url]) => url === '/v1/audio/speech').at(-1);
    assert.equal(JSON.parse(japanese[1].body).voice, 'jf_alpha');
    elements['llm-model'].value = 'llamacpp/alternate';
    elements['llm-model'].onchange(); assert.match(elements['model-status'].textContent, /Pending/);
    const history = elements.history.textContent;
    elements['tts-model'].value = 'compact'; await vm.runInContext('applyModels()', context);
    assert.equal(selectedModels.tts, 'compact');
    assert.equal(selectedModels.llm, 'llamacpp/alternate');
    assert.equal(elements.history.textContent, history);
    assert.match(overlappedTurn.children[1].textContent, /kokoro$/, 'Model switches must not relabel earlier rows');
    elements['enable-asr'].checked = false; await elements['enable-asr'].onchange();
    elements['enable-llm'].checked = false; await elements['enable-llm'].onchange();
    const start = requests.length;
    await elements.send.onclick();
    assert.ok(requests.slice(start).some(([url]) => url === '/v1/audio/speech'));
    assert.ok(!requests.slice(start).some(([url]) => url.includes('/asr/') || url === '/v1/chat/completions'));
    elements['enable-tts'].checked = false; elements['enable-llm'].checked = true;
    await elements['enable-tts'].onchange();
    const chatOnly = requests.length; await elements.send.onclick();
    assert.ok(requests.slice(chatOnly).some(([url]) => url === '/v1/chat/completions'));
    assert.ok(!requests.slice(chatOnly).some(([url]) => url === '/v1/audio/speech'));
    elements['enable-llm'].checked = false;
    const noStages = requests.length; await elements.send.onclick();
    assert.ok(!requests.slice(noStages).some(([url]) => url === '/v1/audio/speech' || url === '/v1/chat/completions' || url.includes('/asr/')));
    assert.ok(elements['measurement-rows'].children.length > 0);
    const originalFetch = context.fetch;
    let finishChat;
    context.fetch = async (url, options) => {
        if (url === '/v1/chat/completions') await new Promise(resolve => finishChat = resolve);
        return originalFetch(url, options);
    };
    elements['enable-llm'].checked = true; elements['enable-tts'].checked = false;
    const beforeCancel = elements.history.textContent;
    const pendingReply = elements.send.onclick(); await tick();
    vm.runInContext('cancelTurn()', context); finishChat(); await pendingReply; await tick(); await tick();
    assert.equal(elements.history.textContent, beforeCancel, 'Cancelled replies must not update the conversation');
    assert.equal(elements.send.disabled, false);
    assert.equal(elements['unload-all'].disabled, false);
    assert.equal(elements['residency-llm'].dataset.state, 'unloaded');
    assert.match(elements.status.textContent, /cancelled/);
    context.fetch = originalFetch;
    elements['correct-language'].checked = false; elements['learning-level'].value = 'B2';
    await elements.send.onclick();
    const latestPrompt = JSON.parse(requests.filter(([url]) => url === '/v1/chat/completions').at(-1)[1].body).messages[0].content;
    assert.match(latestPrompt, /CEFR B2/); assert.match(latestPrompt, /Do not correct/);
    elements['enable-asr'].checked = true; await elements['enable-asr'].onchange();
    elements['auto-send'].checked = false; finalSent = false;
    const replayStart = requests.filter(([url]) => url === '/asr/live/start').length;
    const realSetTimeout = context.setTimeout;
    context.setTimeout = fn => setImmediate(fn);
    try { await vm.runInContext('replayThroughTurns({arrayBuffer: async () => new ArrayBuffer(8)})', context); }
    finally { context.setTimeout = realSetTimeout; }
    assert.equal(elements.transcript.value, 'Bonjour');
    assert.ok(requests.filter(([url]) => url === '/asr/live/start').length > replayStart);
    assert.ok(requests.some(([url]) => url === '/asr/live/token/stop'));
    const getMedia = context.navigator.mediaDevices.getUserMedia;
    let grantMicrophone, cancelledTrack = false;
    context.navigator.mediaDevices.getUserMedia = () => new Promise(resolve => grantMicrophone = resolve);
    const beforeCapture = requests.filter(([url]) => url === '/asr/live/start').length;
    const pendingCapture = elements.record.onclick();
    await elements.record.onclick();
    grantMicrophone({getTracks: () => [{stop: () => cancelledTrack = true}]});
    await pendingCapture;
    assert.ok(cancelledTrack, 'A microphone granted after cancellation must be released');
    assert.equal(requests.filter(([url]) => url === '/asr/live/start').length, beforeCapture);
    context.navigator.mediaDevices.getUserMedia = getMedia;
    console.log('[OK] Tutor settings, transcript review, request cancellation and pending-capture cleanup');
})().catch(error => { console.error(error); process.exitCode = 1; });
