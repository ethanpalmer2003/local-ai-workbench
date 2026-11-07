/* Shared speech transport and native reply observation without models or a browser. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../../..');
const requests = [];
async function adapterContracts() {
    let micRequests = 0, worklet, flush;
    const calls = [], navigations = [], events = {}, transcripts = [], states = [];
    const ctx = vm.createContext({
        Response, Request, Headers, Blob, FormData, TextDecoder, AbortController, Event, URL, console,
        location: {href: 'http://localhost:5003/?ui=llama', origin: 'http://localhost:5003'},
        history: {pushState: (_, __, url) => navigations.push(url), replaceState() {}},
        Audio: class { pause() { this.onpause?.(); } removeAttribute() {} async play() { setImmediate(() => this.onended?.()); } },
        AudioContext: class {
            constructor() { this.sampleRate = 16000; this.audioWorklet = {addModule: async () => {}}; }
            createMediaStreamSource() { return {connect() {}, disconnect() {}}; } async resume() {} async close() {}
        },
        AudioWorkletNode: class { constructor() { this.port = {}; worklet = this; } connect() {} disconnect() {} },
        navigator: {mediaDevices: {getUserMedia: async () => { micRequests++; return {getTracks: () => [{stop() {}}]}; }}, sendBeacon() {}},
        localStorage: {getItem: () => '{}', setItem() {}},
        document: {createElement: () => {throw Error('The native adapter must not create a separate panel');}},
        window: {addEventListener: (name, fn) => events[name] = fn},
        Option: class { constructor(label, value) { this.value = value; } },
        requestAnimationFrame: fn => setImmediate(fn),
        setInterval: fn => {flush = fn; return 1;}, clearInterval() {}, Float32Array, ArrayBuffer, DataView,
        fetch: async (url, options = {}) => {
            calls.push([url, options]);
            if (url === '/asr/status') return Response.json({automatic_turns: true, languages: {common: [{code: 'fr', label: 'French', locale: 'fr-fr', asr_language: 'fr', voice: 'ff_siwis'}]}});
            if (url === '/v1/audio/speech') return new Response('wav');
            if (url === '/asr/live/start') return Response.json({session: 'token'});
            if (url === '/asr/live/token/audio') return Response.json({events: [{type: 'transcript.text.done', text: 'bonjour'}]});
            if (url === '/asr/live/token/stop') return Response.json({});
            return new Response('data: {"choices":[{"delta":{"content":"Salut"},"finish_reason":"stop"}]}\n\n', {headers: {'Content-Type': 'text/event-stream'}});
        }
    });
    for (const name of ['speech_tools.js', 'speech_client.js']) vm.runInContext(fs.readFileSync(path.join(root, 'launchers/shared/browser', name), 'utf8'), ctx);
    vm.runInContext(fs.readFileSync(path.join(root, 'launchers/llamacpp/speech_ui.js'), 'utf8'), ctx);
    await new Promise(resolve => setImmediate(resolve));
    const unbind = ctx.WorkspaceSpeech.bind(async text => transcripts.push(text), state => states.push(state));
    assert.equal(states.at(-1).ready, true); assert.equal(micRequests, 0, 'Opening UI must not access microphone');
    ctx.history.pushState({}, '', '/'); assert.match(navigations[0], /ui=llama/);
    const result = await ctx.fetch('/v1/chat/completions', {headers: {'X-Conversation-Id': 'chat-1'}});
    assert.match(await result.text(), /Salut/);
    for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls.filter(([url]) => url === '/v1/audio/speech').length, 1);
    await ctx.fetch('/v1/chat/completions', {headers: {}}); // Background title generation is silent.
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls.filter(([url]) => url === '/v1/audio/speech').length, 1);
    await ctx.WorkspaceSpeech.toggleCapture(); assert.equal(micRequests, 1);
    worklet.port.onmessage({data: new Float32Array(512)}); await flush();
    assert.deepEqual(transcripts, ['bonjour'], 'VAD turns are delivered directly to the bound native editor');
    assert.equal(states.at(-1).recording, true);
    worklet.port.onmessage({data: new Float32Array(512)}); await flush();
    assert.deepEqual(transcripts, ['bonjour', 'bonjour']);
    await ctx.WorkspaceSpeech.toggleCapture(); assert.ok(calls.some(([url]) => url === '/asr/live/token/stop'));
    unbind(); events.pagehide();
}
const context = vm.createContext({
    Response, Request, Headers, Blob, FormData, TextDecoder, AbortController, console,
    fetch: async (url, options) => {
        requests.push([url, options]);
        return url.endsWith('/speech') ? new Response('wav') : Response.json({text: 'bonjour'});
    }
});
for (const file of ['speech_tools.js', 'speech_client.js']) {
    vm.runInContext(fs.readFileSync(path.join(root, 'launchers/shared/browser', file), 'utf8'), context);
}
(async () => {
    const client = vm.runInContext('new SpeechClient()', context);
    assert.equal((await client.transcribe(new Blob(['wave']), 'fr')).text, 'bonjour');
    assert.equal(requests.at(-1)[1].body.get('language'), 'fr');
    await client.synthesize('salut', {voice: 'ff_siwis', locale: 'fr-fr'});
    assert.equal(JSON.parse(requests.at(-1)[1].body).voice, 'ff_siwis');
    await client.live('token/audio', new ArrayBuffer(1024));
    assert.equal(requests.at(-1)[1].headers['Content-Type'], 'application/octet-stream');
    const text = context.SpeechAssistantText;
    const stream = value => new Response(value, {headers: {'Content-Type': 'text/event-stream'}});
    const original = stream('data: {"choices":[{"delta":{"reasoning_content":"private reasoning"}}]}\n\n'
        + 'data: {"choices":[{"delta":{"content":"Bonjour"}}]}\n\n'
        + 'data: {"choices":[{"delta":{"content":" !"},"finish_reason":"stop"}]}\n\n');
    assert.equal(await text(original.clone()), 'Bonjour !');
    assert.match(await original.text(), /private reasoning/, 'Native UI response remains intact');
    await assert.rejects(text(stream('data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')), /before completion/);
    await assert.rejects(text(stream('data: {"error":{"message":"failed"}}\n\n')), /failed/);
    const abort = new AbortController(); abort.abort();
    await assert.rejects(text(stream('data: [DONE]\n\n'), abort.signal), /abort/i);
    assert.equal(await text(Response.json({choices: [{message: {content: 'Salut'}}]})), 'Salut');
    assert.equal(await text(stream('data: {"choices":[{"delta":{"content":"tool preamble"},"finish_reason":"tool_calls"}]}\n\n')), '');
    await adapterContracts();
    console.log('[OK] Shared ASR/TTS transport, intact SSE, reasoning exclusion, abort and partial-reply guards');
})().catch(error => { console.error(error); process.exitCode = 1; });
