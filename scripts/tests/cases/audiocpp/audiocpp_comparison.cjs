const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function element() {
  return {value: '', textContent: '', children: [], dataset: {}, selected: false, disabled: false,
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    get options() { return this.children; },
    get selectedOptions() { return this.children.filter(child => child.selected); },
    addEventListener() {}, querySelectorAll() { return []; }, remove() {}, setAttribute() {}, removeAttribute() {},
  };
}
const elements = new Map();
const document = {getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
  createElement: element, querySelectorAll() { return []; }};
const requests = [];
const generatedUrls = [];
let active = 0, maximumActive = 0;
const context = vm.createContext({document, console, Blob, AbortController, DOMException,
  URL: class extends URL { static createObjectURL() { const url = `blob:${generatedUrls.length}`; generatedUrls.push(url); return url; } static revokeObjectURL() {} },
  PROXY_URL: 'http://localhost:8888/v1/audio/speech', box: {value: 'One shared input.'},
  activeDefaults: {model: 'breeze', voice: 'voice-a'},
  log: element(), empty: element(), recordings: new Set(), controllers: new Set(),
  generation: 0, pending: Promise.resolve(), performance,
  settings() { return {payload: {stream: true, stream_format: 'sse', options: {temperature: .7, stream_frames_per_event: 16}}}; },
  async fetch(url, options) {
    if (String(url).includes('comparison-catalog')) return {ok: true, async json() { return {
      voices: [{id: 'voice-a', available: true}, {id: 'voice-b', available: true}, {id: 'missing', available: false}],
      models: [{id: 'breeze', installed: true, clone: true}, {id: 'echo', installed: true, clone: true},
        {id: 'absent', installed: false, clone: true}, {id: 'design', installed: true, clone: false}],
    }; }};
    active++; maximumActive = Math.max(maximumActive, active);
    const payload = JSON.parse(options.body); requests.push(payload);
    await new Promise(resolve => setTimeout(resolve, 1)); active--;
    if (payload.model === 'echo' && payload.voice === 'voice-a') return {ok: false, status: 422, async text() { return 'Unsupported session'; }};
    return {ok: true, status: 200, headers: new Headers({'Content-Type': 'audio/wav'}),
      async blob() { return new Blob(['RIFFfixture']); }};
  },
});
for (const name of ['speech_tools.js', 'speech_client.js'])
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../../../launchers/shared/browser', name), 'utf8'), context);
const source = fs.readFileSync(path.join(__dirname, '../../ui/audiocpp_comparison.js'), 'utf8');
vm.runInContext(source, context);

(async () => {
  await document.getElementById('comparison-load').onclick();
  assert.equal(document.getElementById('comparison-models').options.length, 3);
  document.getElementById('comparison-text').value = 'One shared input.';
  document.getElementById('comparison-all-voices').onclick();
  document.getElementById('comparison-all-models').onclick();
  assert.equal(document.getElementById('comparison-voices').selectedOptions.length, 2);
  assert.equal(document.getElementById('comparison-models').selectedOptions.length, 2);
  document.getElementById('comparison-run').onclick();
  await context.pending;
  assert.equal(requests.length, 4);
  assert.equal(maximumActive, 1);
  assert.equal(generatedUrls.length, 3, 'failed requests must not create a player');
  assert.deepEqual(requests.map(request => [request.model, request.voice]), [
    ['breeze', 'voice-a'], ['breeze', 'voice-b'], ['echo', 'voice-a'], ['echo', 'voice-b'],
  ]);
  for (const request of requests) {
    assert.equal(request.input, 'One shared input.'); assert.equal(request.stream, false);
    assert.equal(request._comparison, true);
    assert.equal(request.response_format, 'wav'); assert.equal(request.stream_format, undefined);
    assert.equal(request.options.temperature, .7); assert.equal(request.options.stream_frames_per_event, undefined);
  }
  const cards = context.log.children[0].children[2].children;
  assert.match(cards[2].children[1].textContent, /Failed: 422/);
  assert.equal(cards[0].children[2].controls, true);
  assert.equal(cards[0].children[2].autoplay, undefined);
  assert.equal(document.getElementById('comparison-run').disabled, false);
  const before = requests.length;
  document.getElementById('comparison-run').onclick();
  document.getElementById('comparison-stop').onclick();
  await context.pending;
  assert.equal(requests.length, before, 'canceled queued batches must not generate');
  assert.match(document.getElementById('comparison-status').textContent, /canceled/i);
  document.getElementById('comparison-clear').onclick();
  assert.equal(context.recordings.size, 0);
  console.log('PASS: voice/model matrix, missing choices, serial WAV requests, per-card failures, no autoplay, cancellation and cleanup');
})().catch(error => { console.error(error); process.exitCode = 1; });

