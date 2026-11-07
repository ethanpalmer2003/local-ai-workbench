const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const controls = Object.fromEntries(['enabled','buffer','rate','transport','text-mode','text-limit','tone-tags','tone-help','policy','frames','lookahead','stop','close','status']
    .map(id => ['#kas-' + id, {id:'kas-' + id, value:'', checked:true, type:'number', textContent:''}]));
controls['#kas-enabled'].type = 'checkbox';
controls['#kas-tone-tags'].type = 'checkbox';
controls['#kas-tone-tags'].checked = false;
controls['#kas-buffer'].value = '1500';
controls['#kas-rate'].value = '24000';
controls['#kas-text-mode'].value = 'whole';
controls['#kas-text-limit'].value = '80';
const listeners = {};
const node = () => ({style:{}, append() {}, setAttribute() {}, addEventListener(event, listener) { listeners[event] = listener; },
    querySelector(id) { return controls[id]; }, querySelectorAll() { return Object.values(controls); }});
const starts = [];
let clock = 0;
const audio = {get currentTime() { return clock; }, async resume() {},
    createBuffer(channels, samples, rate) { return {duration:samples/rate, getChannelData() { return new Float32Array(samples); }}; },
    createBufferSource() { return {connect() {}, start(at) { starts.push(at); }, stop() { this.onended(); }}; }};
const scope = vm.createContext({console, document:{createElement:node, body:node(), querySelector:node},
    window:{koboldAudioSettings:{streaming_enabled:true,playback_buffer_ms:1500,pcm_sample_rate:24000,text_mode:"whole",text_limit:80}, addEventListener() {}},
    localStorage:{getItem() {return null;}, setItem() {}}, closeTopNav() {},
    ttsAudioContext:audio, ttsMasterGain:{}, tts_is_processing:false, tts_is_playing:false,
    tts_speak_input_queue:[], tts_speak_output_queue:[], update_submit_button() {},
    performance:{now() {return clock*1000;}}, AbortController, TextDecoder, Uint8Array, DataView, ArrayBuffer, atob, Intl, URL, location:{href:'http://127.0.0.1:5001/'}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../../../launchers/shared/browser/pcm_audio.js'),'utf8'),scope);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../../../launchers/koboldcpp/kobold_audio.js'),'utf8'),scope);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../../../launchers/koboldcpp/kobold_streaming.js'),'utf8'),scope);
const api = scope.window.koboldAudioStream;
scope.window.koboldAudioSettings.audioProxyPort = 8888;
scope.location.href = 'http://192.168.1.20:5001/';
assert.equal(api.speechEndpoint('http://127.0.0.1:8888/v1/audio/speech'),'http://192.168.1.20:5001/v1/audio/speech');
assert.equal(api.speechEndpoint('http://example.test/v1/audio/speech'),'http://example.test/v1/audio/speech');
const text = 'Hello there. This is another sentence. We can keep talking.';
assert.deepEqual(Array.from(api.chunkText(text)),[text]);
controls['#kas-text-mode'].value='narration';
assert.equal(api.useTextQueue(false), false);
assert.equal(api.useTextQueue(true), true);
const originalText = 'Mr. Smith says "Hello." Then goes! Next? Yes.\nAnother line.\n\nDone.';
const originalChunks = originalText.replaceAll('. ', '.\n').replaceAll('! ', '!\n').replaceAll('? ', '?\n')
    .split('\n').map(chunk => chunk.trim()).filter(Boolean);
assert.deepEqual(Array.from(api.chunkText(originalText)), originalChunks);
controls['#kas-text-mode'].value='narration_on';
assert.equal(api.useTextQueue(false), true);
assert.equal(api.useTextQueue(true), true);
assert.deepEqual(Array.from(api.chunkText(originalText)), originalChunks);
listeners.change();
assert.equal(controls['#kas-text-limit'].disabled, true);
assert.equal(controls['#kas-buffer'].disabled, false);
scope.window.koboldAudioSettings.tone_tags_supported = true;
controls['#kas-tone-tags'].checked = true;
controls['#kas-text-mode'].value='narration';
assert.deepEqual(Array.from(api.chunkText('[Tone: happy] Hi! Again. [Tone: sad] Bye.')),
    ['[Tone: happy] Hi!', '[Tone: happy] Again.', '[Tone: sad] Bye.']);
controls['#kas-text-mode'].value='sentences';
assert.equal(api.useTextQueue(false), true);
assert.equal(api.chunkText(text).length,3);
assert.deepEqual(Array.from(api.chunkText('[Tone: cheerful] Hello! Still happy. [Tone: sad] Oh no.')),
    ['[Tone: cheerful] Hello!', '[Tone: cheerful] Still happy.', '[Tone: sad] Oh no.']);
assert.equal(api.toneInstruction('[Tone: cheerful] "Hello!"'), 'cheerful');
controls['#kas-tone-tags'].checked = false;
assert.equal(api.toneInstruction('[Tone: cheerful] Hello!'), null);
assert.deepEqual(Array.from(api.chunkText('[Tone: cheerful] Hello! [Tone: sad] Goodbye.')), ['Hello!', 'Goodbye.']);
controls['#kas-tone-tags'].checked = true;
controls['#kas-text-mode'].value='whole';
assert.equal(api.useTextQueue(false), false);
assert.equal(api.useTextQueue(true), false);
assert.deepEqual(Array.from(api.chunkText('[Tone: cheerful] Hello. [Tone: sad] Goodbye.')),
    ['Hello.  Goodbye.']);
controls['#kas-text-mode'].value='bounded';
listeners.change();
assert.equal(controls['#kas-text-limit'].disabled, false);
controls['#kas-enabled'].checked = false;
listeners.change();
assert.equal(controls['#kas-text-limit'].disabled, true);
assert.equal(controls['#kas-buffer'].disabled, true);
controls['#kas-enabled'].checked = true;
listeners.change();
const chunks = Array.from(api.chunkText(text+' '+text));
assert.ok(chunks.every(chunk => chunk.length<=80));
assert.equal(chunks.join(' '),text+' '+text);

(async () => {
    const event = 'data: '+JSON.stringify({type:'speech.audio.delta',audio:Buffer.alloc(4800).toString('base64')})+'\n\n';
    const packets = [event.slice(0,29),event.slice(29),event,'data: [DONE]\n\n'];
    let index=0;
    let sent;
    scope.fetch = async (url, init) => {
        sent=JSON.parse(init.body);
        return {ok:true,headers:{get() {return 'text/event-stream';}},body:{getReader() {return {
            async read() {if(index===2) clock=0.8; return index===packets.length ? {done:true} : {value:new TextEncoder().encode(packets[index++]),done:false};},
            async cancel() {}, releaseLock() {},
        };}}};
    };
    await api.speak('/v1/audio/speech', {input:text}, {}, false, false);
    assert.equal(sent.stream,true);
    assert.equal(sent.stream_format,'audio'); // Launcher-inherited raw request can still receive SSE.
    assert.equal(starts.length,2);
    assert.ok(Math.abs(starts[1]-starts[0]-0.1)<1e-9);
    assert.match(controls['#kas-status'].textContent,/0 underruns.*generation complete/);
    api.stop();
    controls['#kas-transport'].value = 'sse'; index = 0;
    await api.speak('/v1/audio/speech', {input:text}, {}, false, false);
    assert.equal(sent.stream_format, 'sse', 'explicit SSE override remains available');
    api.stop();
    assert.equal(scope.tts_is_playing,false);
    scope.fetch = (url, init) => new Promise((resolve,reject) => {
        const abort = () => reject(Object.assign(new Error('aborted'),{name:'AbortError'}));
        if (init.signal.aborted) abort(); else init.signal.addEventListener('abort',abort);
    });
    const pending = api.speak('/v1/audio/speech',{input:text},{},false,false);
    await Promise.resolve();
    api.stop(); await pending;
    assert.equal(scope.tts_is_processing,false);
    // The single-toggle PR calls the same bridge with no advanced config.
    let requestBody, downloaded, embedded;
    scope.tts_download = bytes => { downloaded = bytes; };
    scope.tts_embed_audio = bytes => { embedded = bytes; };
    scope.fetch = async (url, init) => {
        requestBody = JSON.parse(init.body);
        return {ok:true,headers:{get() {return 'audio/pcm';}},body:{getReader() {
            let sent = false;
            return {async read() { if (sent) return {done:true}; sent=true; return {value:new Uint8Array(4800),done:false}; },
                async cancel() {}, releaseLock() {}};
        }}};
    };
    await scope.window.koboldAudioPlayback.speak('/v1/audio/speech', {input:text}, {}, true, true);
    assert.equal(requestBody.stream_format, 'audio');
    assert.equal(requestBody.options, undefined);
    assert.equal(requestBody.stream, true);
    assert.equal(downloaded, embedded);
    assert.equal(new DataView(downloaded).getUint32(40,true), 4800);
    await scope.window.koboldAudioPlayback.speak('https://api.openai.com/v1/audio/speech', {input:text}, {}, false, false);
    assert.equal(requestBody.stream, undefined);
    await scope.window.koboldAudioPlayback.speak('https://api.openai.com.example.test/v1/audio/speech', {input:text}, {}, false, false);
    assert.equal(requestBody.stream, true);
    let deliver, staleCanceled = false;
    scope.fetch = () => new Promise(resolve => { deliver = resolve; });
    const stale = scope.window.koboldAudioPlayback.speak('/v1/audio/speech', {input:text}, {}, false, false);
    await new Promise(resolve => setImmediate(resolve));
    scope.window.koboldAudioPlayback.stop();
    const count = starts.length;
    deliver({body:{async cancel() { staleCanceled=true; }}});
    await stale;
    assert.ok(staleCanceled);
    assert.equal(starts.length, count, 'late fetch cannot resurrect stopped audio');
    assert.equal(scope.tts_is_processing, false);
    console.log('PASS: text grouping, request format, split SSE events, contiguous audio, cancellation and busy-state recovery');
})().catch(error => {console.error(error);process.exitCode=1;});

