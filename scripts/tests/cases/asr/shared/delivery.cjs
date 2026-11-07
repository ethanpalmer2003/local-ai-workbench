const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../../../../launchers/shared/browser');
const calls = [], played = [], modes = [];
let rejectStreaming = false, rejectChunked = false, failAfterOutput = false;
const ctx = vm.createContext({
    Response, Request, Headers, Blob, FormData, TextDecoder, AbortController, setTimeout, console,
    fetch: async (url, options) => {
        const payload = JSON.parse(options.body); calls.push([url, payload]);
        if (payload.stream && rejectStreaming) return new Response('unsupported stream format', {status: 415});
        if (!payload.stream && rejectChunked) { rejectChunked = false; return new Response('unsupported format', {status: 415}); }
        if (url.includes('chat/completions')) return Response.json({choices: [{message: {content: 'Bonjour'}}]});
        return new Response(payload.input, {headers: {'Content-Type': payload.stream ? 'audio/pcm' : 'audio/wav'}});
    }
});
for (const name of ['speech_tools.js', 'speech_client.js']) vm.runInContext(fs.readFileSync(path.join(root, name), 'utf8'), ctx);
const tick = () => new Promise(resolve => setImmediate(resolve));
(async () => {
    const client = vm.runInContext('new SpeechClient()', ctx), profile = {voice: 'ff_siwis', locale: 'fr-fr'};
    client.policy = {llm: {mode: 'streaming'}, tts: {mode: 'streaming', supported: ['streaming', 'chunked', 'whole']}};
    client.prepare = async () => {client.player = {sources: new Set(), stop() {}, consume: async response => {
        played.push(await response.text()); if (failAfterOutput) throw Error('late stream failure');
    }};};
    client.whole = async blob => {played.push(await blob.text());};
    await client.say('Bonjour.', profile, undefined, {onMode: mode => modes.push(mode)});
    assert.equal(calls[0][1].stream, true); assert.equal(modes.at(-1), 'streaming');
    rejectStreaming = true; calls.length = played.length = 0;
    await client.say('Bonjour. Comment allez-vous?', profile, undefined, {onMode: mode => modes.push(mode)});
    assert.deepEqual(calls.map(call => call[1].stream), [true, false, false]);
    assert.equal(modes.at(-1), 'chunked'); assert.equal(played.length, 2);
    calls.length = played.length = 0; rejectChunked = true;
    await client.say('Bonjour. Encore.', profile, undefined, {onMode: mode => modes.push(mode)});
    assert.equal(modes.at(-1), 'whole'); assert.equal(played.length, 1);
    rejectStreaming = false; failAfterOutput = true; calls.length = 0;
    await assert.rejects(client.say('Bonjour.', profile), /late stream failure/);
    assert.equal(calls.length, 1, 'Never retry after audio output begins');
    failAfterOutput = false; client.policy.tts.mode = 'chunked'; calls.length = played.length = 0;
    const turn = client.utterance(profile);
    turn.feed('Bonjour. '); await tick();
    assert.ok(calls.length, 'First sentence starts before the whole reply is finished');
    turn.feed('Comment allez-vous?'); await turn.finish(); assert.equal(played.length, 2);
    client.policy.tts.mode = 'whole'; calls.length = 0;
    const buffered = client.utterance(profile); buffered.feed('Bonjour. '); await tick();
    assert.equal(calls.length, 0); buffered.feed('Encore.'); await buffered.finish(); assert.equal(calls.length, 1);
    rejectStreaming = true; calls.length = 0;
    assert.equal(await client.chat({messages: []}), 'Bonjour');
    assert.deepEqual(calls.map(call => call[1].stream), [true, false]);
    client.policy.llm.mode = 'whole'; calls.length = 0;
    const response = await client.chatResponse('/v1/chat/completions', {body: JSON.stringify({stream: true})}, ctx.fetch);
    assert.equal(calls[0][1].stream, false);
    assert.match(response.headers.get('content-type'), /event-stream/);
    assert.match(await response.text(), /Bonjour/, 'Whole-request override remains compatible with native UI');
    const abort = new AbortController(); abort.abort(); calls.length = 0;
    await assert.rejects(client.say('No request', profile, abort.signal), /abort/i);
    assert.equal(calls.length, 0);
    console.log('[OK] Streaming/chunked/whole negotiation, sentence pipeline, overrides and no replay after output');
})().catch(error => {console.error(error); process.exitCode = 1;});
