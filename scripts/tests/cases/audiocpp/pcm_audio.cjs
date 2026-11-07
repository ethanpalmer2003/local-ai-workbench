const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

let clock = 0;
const buffers = [], starts = [];
const audio = {get currentTime() { return clock; }, destination: {},
    createBuffer(channels, frames, rate) {
        const data = Array.from({length: channels}, () => new Float32Array(frames));
        const buffer = {duration: frames / rate, data, getChannelData(ch) { return data[ch]; }};
        buffers.push(buffer); return buffer;
    },
    createBufferSource() { return {connect() {}, start(at) { starts.push(at); }, stop() { this.onended(); }}; },
    async decodeAudioData() { return this.createBuffer(1, 2400, 24000); },
};
const scope = vm.createContext({console, TextDecoder, Uint8Array, ArrayBuffer, DataView, atob,
    performance: {now: () => clock * 1000}});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../../../launchers/shared/browser/pcm_audio.js'), 'utf8'), scope);
const {Player, wav} = scope.PcmAudio;
const pcm = Buffer.from([0, 64, 0, 192, 255, 127, 0, 128]);

function response(bytes, type = 'audio/pcm', stride = 1) {
    let at = 0, canceled = false, released = false;
    return {headers: {get: () => type}, arrayBuffer: async () => bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
        body: {getReader() { return {
            async read() {
                if (at >= bytes.length) return {done: true};
                const value = bytes.subarray(at, at + stride); at += stride; return {value, done: false};
            }, async cancel() { canceled = true; }, releaseLock() { released = true; },
        }; }}, cleaned: () => canceled && released};
}
function sse(bytes, done = true) {
    // PCM frames and CRLF delimiters may both cross network/event boundaries.
    const packets = [bytes.subarray(0, 1), bytes.subarray(1, 5), bytes.subarray(5)];
    const text = packets.map(part => `data: ${JSON.stringify({type: 'speech.audio.delta', audio: part.toString('base64')})}\r\n\r\n`).join('') +
        (done ? 'data: [DONE]\r\n\r\n' : '');
    return response(Buffer.from(text), 'text/event-stream');
}
async function consume(res, config = {}) {
    buffers.length = 0; starts.length = 0;
    const player = new Player(audio);
    const result = await player.consume(res, {capture: true, ...config});
    if (!res.headers.get('Content-Type').includes('mpeg')) assert.ok(res.cleaned?.() ?? true);
    return result;
}

(async () => {
    const raw = await consume(response(pcm));
    const events = await consume(sse(pcm));
    assert.deepEqual(Buffer.from(raw.recording), Buffer.from(events.recording));
    assert.equal(events.duration, 4 / 24000);
    assert.equal(buffers[0].data[0][0], .5);
    assert.equal(buffers[0].data[0][1], -.5);
    assert.equal(starts[0], .32, 'PR defaults use a 300 ms startup buffer plus scheduling margin');
    const short = await consume(response(pcm.subarray(0, 2)));
    assert.equal(new DataView(short.recording).getUint32(40, true), 2);
    const stereoWav = Buffer.from(wav([pcm], 16000, 2));
    const stereo = await consume(response(Buffer.concat([stereoWav, Buffer.from('LISTmetadata')]), 'audio/wav'));
    assert.deepEqual(Buffer.from(stereo.recording), stereoWav, 'finite WAV data excludes trailing metadata');
    assert.equal(buffers[0].data.length, 2);
    assert.equal(buffers[0].data[0][0], .5);
    assert.equal(buffers[0].data[1][0], -.5);
    const unknownLength = Buffer.from(stereoWav); unknownLength.writeUInt32LE(0xffffffff, 40);
    assert.deepEqual(Buffer.from((await consume(response(unknownLength, 'audio/wav'))).recording), stereoWav);
    await assert.rejects(consume(response(pcm.subarray(0, 3))), /Incomplete PCM frame/);
    await assert.rejects(consume(sse(pcm, false)), /completion marker/);
    await assert.rejects(consume(response(stereoWav.subarray(0, -1), 'audio/wav')), /Truncated WAV/);
    await assert.rejects(consume(response(stereoWav.subarray(0, 40), 'audio/wav')), /Incomplete audio header/);
    await assert.rejects(consume(response(pcm, 'application/json')), /Content-Type/);
    const floatWav = Buffer.from(stereoWav); floatWav.writeUInt16LE(3, 20);
    await assert.rejects(consume(response(floatWav, 'audio/wav')), /16-bit PCM/);
    const encoded = await consume(response(pcm, 'audio/mpeg'));
    assert.deepEqual(Buffer.from(encoded.recording), pcm, 'compressed fallback preserves original bytes');

    const player = new Player(audio), controller = new AbortController();
    let finishRead, released = false;
    const pendingResponse = {headers: {get: () => 'audio/pcm'}, body: {getReader: () => ({
        read: () => new Promise(resolve => { finishRead = resolve; }),
        async cancel() { finishRead?.({done: true}); }, releaseLock() { released = true; },
    })}};
    const pending = player.consume(pendingResponse, {signal: controller.signal});
    controller.abort(); player.stop();
    await assert.rejects(pending, {name: 'AbortError'});
    assert.ok(released);
    assert.equal(player.sources.size, 0);
    console.log('PASS: shared HTTP/SSE PCM, byte boundaries, stereo WAV, completion/errors, encoded fallback and cancellation');
})().catch(error => {console.error(error); process.exitCode = 1;});
