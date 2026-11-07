// Run with node tests/cases/regression/audiocpp_test_page.cjs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const elements = new Map();
const windowEvents = {};
function element() {
  return {_value: '', get value() { return this._value; }, set value(value) { this._value = String(value); },
    textContent: '', children: [], listeners: {}, parentElement: {append() {}},
    append(...items) { this.children.push(...items); }, addEventListener(event, handler) { this.listeners[event] = handler; }, remove() {},
    replaceChildren() {}, reportValidity() { return true; }};
}
const document = {
  documentElement: {dataset: {}},
  getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
  createElement: element, querySelectorAll() { return []; },
};
const starts = [];
const audioContext = {
  currentTime: 0,
  createBuffer(channels, samples, rate) { return {duration: samples / rate, getChannelData() { return new Float32Array(samples); }}; },
  createBufferSource() { return {connect() {}, start(at) { starts.push(at); }}; },
};
const context = vm.createContext({document, window: {addEventListener(event, handler) { windowEvents[event] = handler; }}, console,
  Option: class { constructor(text, value) { this.textContent = text; this.value = value; } },
  URL, Blob, TextDecoder, Uint8Array, ArrayBuffer, DataView, atob, AbortController,
  performance: {now() { return audioContext.currentTime * 1000; }}, audioContext});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../../../launchers/shared/browser/pcm_audio.js'), 'utf8'), context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../../../launchers/shared/browser/speech_tools.js'), 'utf8'), context);
const html = fs.readFileSync(path.join(__dirname, '../../ui/speech.html'), 'utf8');
const controller = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]
  .map(match => match[1]).find(block => block.includes('function settings'));
assert.ok(controller, 'speech.html must keep its inline controller script');
vm.runInContext(controller, context);
vm.runInContext('context = audioContext', context);
assert.equal(document.getElementById('buffer').value, '');
assert.equal(vm.runInContext('defaultsLoaded', context), false);
assert.equal(vm.runInContext('activeDefaults', context), undefined);
document.getElementById('extra').value = '{}';
document.getElementById('mode').value = 'buffered';
document.getElementById('buffer').value = '500';
document.getElementById('rate').value = '24000';
const config = vm.runInContext('settings()', context);
assert.equal(config.payload.stream, false);
assert.equal(config.payload.response_format, 'wav');
assert.equal(config.payload.stream_format, undefined);

document.getElementById('voice').value = 'voice-a';
document.getElementById('frames').value = '16';
vm.runInContext('updateResponseMode()', context);
assert.equal(document.getElementById('streaming-settings').disabled, true);
assert.equal(vm.runInContext('settings()', context).payload.voice, 'voice-a');
assert.equal(vm.runInContext('settings()', context).payload.options.stream_frames_per_event, undefined);
document.getElementById('mode').value = 'stream';
vm.runInContext('updateResponseMode()', context);
assert.equal(document.getElementById('streaming-settings').disabled, false);
assert.equal(vm.runInContext('settings()', context).payload.voice, 'voice-a');
assert.equal(vm.runInContext('settings()', context).payload.options.stream_frames_per_event, 16);
document.getElementById('instr').value = 'cheerful';
const instructionConfig = vm.runInContext('settings()', context);
assert.equal(instructionConfig.payload.options.instruction, 'cheerful');
assert.equal(instructionConfig.payload.options.instruct, undefined);

async function playback(bufferSeconds) {
  starts.length = 0;
  audioContext.currentTime = 0;
  vm.runInContext('player = undefined', context);
  const pcm = Buffer.alloc(4800).toString('base64'); // 100 ms of 24 kHz mono PCM
  const event = `data: ${JSON.stringify({type: 'speech.audio.delta', audio: pcm})}\n\n`;
  const packets = [event.slice(0, 30), event.slice(30), event, 'data: [DONE]\n\n'];
  let index = 0;
  const response = {headers: {get() { return 'text/event-stream'; }}, body: {getReader() { return {
    async read() {
      if (index === 2) audioContext.currentTime = 0.25;
      if (index === packets.length) return {done: true};
      return {value: new TextEncoder().encode(packets[index++]), done: false};
    }, async cancel() {}, releaseLock() {},
  }; }}};
  const status = element();
  context.response = response; context.status = status;
  context.config = {rate: 24000, bufferSeconds};
  await vm.runInContext('playStream(response, status, 0, generation, config)', context);
  assert.equal(starts.length, 2);
  return status.textContent;
}

(async () => {
  const servedConfig = {
    model: 'audiocpp/breeze-tts-2-q4_0', voice: 'voice-a', streaming_enabled: true, streaming: { playback_buffer_ms: 2000,
      pcm_sample_rate: 24000, transport: 'audio', stream_frames_per_event: 16, stream_lookahead_margin: null, stream_chunk_policy: null},
    proxy_defaults: {guidance_scale: 1, instruction: ''},
    packaged_defaults: {request: {temperature: .9, stream_lookahead_margin: 12}},
  };
  context.fetch = async (url, options) => {
    assert.equal(options.cache, 'no-store');
    return {ok: true, async json() { return servedConfig; }};
  };
  await windowEvents.DOMContentLoaded();
  assert.equal(document.getElementById('buffer').value, '');
  assert.equal(document.getElementById('buffer').placeholder, '2000');
  assert.equal(document.getElementById('frames').value, '');
  assert.equal(document.getElementById('frames').placeholder, '16');
  assert.equal(document.getElementById('lookahead').value, '');
  assert.equal(document.getElementById('tts-model').value, 'audiocpp/breeze-tts-2-q4_0');
  assert.match(document.getElementById('defaults-status').textContent, /Defaults loaded/);
  assert.equal(document.getElementById('speak').disabled, false);
  assert.equal(document.getElementById('temperature').value, '');
  assert.equal(document.getElementById('temperature').placeholder, '0.9');
  assert.match(document.getElementById('temperature').title, /GGUF fallback/);
  assert.equal(document.getElementById('lookahead').placeholder, '12');
  assert.equal(document.getElementById('gs').placeholder, '1');
  assert.equal(vm.runInContext('settings()', context).bufferSeconds, 2);
  assert.equal(vm.runInContext('settings()', context).rate, 24000);
  assert.equal(vm.runInContext('settings()', context).payload.stream_format, 'audio');
  document.getElementById('transport').value = 'sse';
  assert.equal(vm.runInContext('settings()', context).payload.stream_format, 'sse');
  document.getElementById('transport').value = '';
  assert.equal(vm.runInContext('settings()', context).payload.model, 'audiocpp/breeze-tts-2-q4_0');
  assert.equal(vm.runInContext('settings()', context).payload.options.temperature, undefined);
  document.getElementById('temperature').value = '.4';
  document.getElementById('extra').value = '{"top_k":7}';
  servedConfig.streaming.playback_buffer_ms = 750;
  servedConfig.packaged_defaults.request.temperature = 1.2;
  await document.getElementById('tts-model').onchange();
  assert.equal(document.getElementById('temperature').value, '', 'model selection resets overrides');
  assert.equal(document.getElementById('temperature').placeholder, '1.2');
  await document.getElementById('defaults').onclick();
  assert.equal(document.getElementById('buffer').placeholder, '750', 'refresh reads changed code defaults');
  assert.equal(vm.runInContext('settings()', context).bufferSeconds, .75);
  assert.equal(document.getElementById('temperature').value, '');
  assert.equal(document.getElementById('extra').value, '{}');
  servedConfig.selected_model = 'audiocpp/ming3-tts-0.5b-q8_0';
  servedConfig.instruction_option = 'instruct';
  servedConfig.proxy_defaults = {};
  servedConfig.server_request_defaults = {seed: 1895, language: 'en'};
  servedConfig.packaged_defaults.request.instruct = 'A warm voice';
  servedConfig.streaming.pcm_sample_rate = 44100;
  document.getElementById('tts-model').value = servedConfig.selected_model;
  await document.getElementById('tts-model').onchange();
  document.getElementById('instr').value = 'A calm voice';
  const ming = vm.runInContext('settings()', context);
  assert.equal(ming.payload.model, servedConfig.selected_model);
  assert.equal(ming.rate, 44100);
  assert.equal(ming.payload.options.instruct, 'A calm voice');
  assert.equal(ming.payload.options.instruction, undefined);
  assert.equal(document.getElementById('instr').placeholder, 'A warm voice');
  assert.equal(document.getElementById('seed').placeholder, '1895');
  servedConfig.selected_model = 'audiocpp/ming3-audio-tiny-q4_k';
  servedConfig.instruction_option = null;
  servedConfig.streaming_supported = false;
  servedConfig.streaming_enabled = false;
  document.getElementById('tts-model').value = servedConfig.selected_model;
  await document.getElementById('tts-model').onchange();
  document.getElementById('mode').value = 'stream';
  document.getElementById('instr').value = 'unsupported';
  const heavyMing = vm.runInContext('settings()', context);
  assert.equal(heavyMing.payload.stream, false);
  assert.equal(heavyMing.payload.response_format, 'wav');
  assert.equal(heavyMing.payload.options.instruction, undefined);
  assert.equal(document.getElementById('instr').disabled, true);
  assert.equal(document.getElementById('fast').disabled, true);
  servedConfig.practice_gateway = true; servedConfig.practice_url = '/practice';
  await document.getElementById('defaults').onclick();
  assert.equal(document.getElementById('comparison').hidden, true);
  assert.equal(document.getElementById('restart-section').hidden, true);
  assert.equal(document.getElementById('mode').disabled, true);
  assert.ok(!html.includes('<iframe'));
  assert.ok(html.includes('id="enable-llm"'));
  vm.runInContext('defaultsLoaded = false', context);
  document.getElementById('speak').disabled = true;
  context.fetch = async () => { throw new Error('proxy unavailable'); };
  await document.getElementById('defaults').onclick();
  assert.equal(document.getElementById('speak').disabled, true);
  assert.match(document.getElementById('defaults-status').textContent, /generation disabled/);
  assert.match(await playback(0.05), /1 playback underruns/);
  assert.match(await playback(0.5), /0 playback underruns/);
  assert.ok(Math.abs(starts[1] - starts[0] - 0.1) < 1e-9, 'chunks must remain contiguous');
  const wav = await vm.runInContext('PcmAudio.wav([new Uint8Array(4800)], 24000)', context);
  assert.equal(new DataView(wav).getUint32(24, true), 24000);
  assert.equal(new DataView(wav).getUint32(40, true), 4800);
  console.log('PASS: buffered request, split SSE parsing, underrun detection, startup buffering, contiguous scheduling, WAV capture');
})().catch(error => { console.error(error); process.exitCode = 1; });

