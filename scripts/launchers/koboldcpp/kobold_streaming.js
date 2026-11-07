/* Local Kobold Lite OpenAI speech streaming integration. */
(() => {
    const settings = window.koboldAudioSettings;
    const panel = document.createElement('section');
    panel.id = 'kas-panel';
    panel.hidden = true;
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Audio Streaming settings');
    panel.innerHTML = `<style>
        #kas-panel {
            position: fixed; top: 65px; right: 16px; z-index: 99999;
            display: flex; flex-direction: column; width: 480px;
            max-width: calc(100vw - 32px); max-height: calc(100vh - 81px);
            max-height: calc(100dvh - 81px); overflow: hidden;
            background: #20242c; color: #e5e9f0; color-scheme: dark;
            border: 1px solid #7d899d; border-radius: 8px;
            box-shadow: 0 8px 32px #0008; font: 13px/1.5 system-ui;
        }
        #kas-panel[hidden] { display: none; }
        #kas-panel, #kas-panel * { box-sizing: border-box; }
        #kas-panel .kas-header { position: relative; padding: 16px 96px 12px 16px; border-bottom: 1px solid #424b5c; }
        #kas-panel h3 { color: #f4f6fa; font-size: 20px; line-height: 1.3; margin: 0; }
        #kas-panel .kas-subtitle { margin: 4px 0 0; color: #b8c2d1; }
        #kas-panel #kas-close { position: absolute; top: 12px; right: 12px; min-height: 44px; margin: 0; }
        #kas-panel .kas-content { min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 16px; }
        #kas-panel fieldset { min-width: 0; margin: 0 0 16px; padding: 12px; border: 1px solid #566175; border-radius: 6px; }
        #kas-panel fieldset:last-child { margin-bottom: 0; }
        #kas-panel legend { padding: 0 6px; color: #f4f6fa; font-weight: 600; }
        #kas-panel .kas-field { display: grid; gap: 4px; margin-bottom: 12px; }
        #kas-panel .kas-field:last-child { margin-bottom: 0; }
        #kas-panel .kas-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
        #kas-panel .kas-grid .kas-field { margin-bottom: 0; }
        #kas-panel p { margin: 0 0 12px; }
        #kas-panel .kas-help { color: #b8c2d1; font-size: 12px; }
        #kas-panel .kas-footer { padding: 12px 16px; border-top: 1px solid #424b5c; }
        #kas-panel #kas-status { margin: 8px 0 0; overflow-wrap: anywhere; }
        #kas-panel input:not([type="checkbox"]), #kas-panel select, #kas-panel button {
            background: #303744 !important; color: #f4f6fa !important;
            border: 1px solid #7d899d; border-radius: 4px; padding: 8px;
            font: inherit; line-height: 1.4; margin: 0; min-width: 0;
            max-width: 100%; -webkit-text-fill-color: #f4f6fa;
        }
        #kas-panel .kas-field input, #kas-panel select { width: 100%; }
        #kas-panel option, #kas-panel optgroup { background: #303744; color: #f4f6fa; }
        #kas-panel input::placeholder { color: #b8c2d1; opacity: 1; -webkit-text-fill-color: #b8c2d1; }
        #kas-panel input[type="checkbox"] { accent-color: #83b9ff; }
        #kas-panel button { cursor: pointer; }
        #kas-panel :disabled { opacity: .5; cursor: not-allowed; }
        #kas-panel button:hover { background: #414d60 !important; }
        #kas-panel input:focus-visible, #kas-panel select:focus-visible, #kas-panel button:focus-visible {
            outline: 2px solid #a5ccff; outline-offset: 2px;
        }
        @media (max-width: 600px) {
            #kas-panel { top: max(12px, env(safe-area-inset-top)); right: 12px; max-width: calc(100vw - 24px);
                max-height: calc(100vh - 24px); max-height: calc(100dvh - 24px - env(safe-area-inset-top) - env(safe-area-inset-bottom)); }
            #kas-panel .kas-grid { grid-template-columns: 1fr; }
        }
    </style>
        <header class="kas-header">
            <h3>Audio Streaming</h3><p class="kas-subtitle">Local additions</p>
            <button id="kas-close" type="button" aria-label="Close Audio Streaming settings">Close</button>
        </header>
        <div class="kas-content">
            <fieldset><legend>Text requests</legend>
                <p class="kas-help">Default follows Media's Narration streaming. Per-sentence tone tags need it on or Separate sentences mode.</p>
                <label class="kas-field">Request mode <select id="kas-text-mode"><optgroup label="Original Kobold behavior"><option value="narration">Follow Media Narration streaming</option><option value="whole">Wait for full reply · one TTS request</option><option value="narration_on">Narration streaming ON - original chunks</option></optgroup><optgroup label="Local additions"><option value="bounded">Group text up to character limit</option><option value="sentences">Separate sentences (browser segmenter)</option></optgroup></select></label>
                <label class="kas-field">Character limit <input id="kas-text-limit" type="number" min="80" max="2000"><span class="kas-help">Only used by the local character-group mode.</span></label>
                <label><input id="kas-tone-tags" type="checkbox"> Use tone tags as sentence instructions</label>
                <p id="kas-tone-help" class="kas-help">Optional. Available with Breeze 2 in Follow narration or Separate sentences mode.</p>
            </fieldset>
            <fieldset><legend>Audio playback</legend>
                <label><input id="kas-enabled" type="checkbox" checked> Stream OpenAI TTS audio</label>
                <p class="kas-help">Local addition. Turn off to use original Kobold audio playback and Media text controls.</p>
                <div class="kas-grid">
                    <label class="kas-field">Playback buffer (ms) <input id="kas-buffer" type="number" min="0" max="10000" step="50" value="${settings.playback_buffer_ms}"></label>
                    <label class="kas-field">PCM sample rate (Hz) <input id="kas-rate" type="number" min="8000" value="${settings.pcm_sample_rate}"></label>
                </div>
            </fieldset>
            <fieldset><legend>Server streaming options</legend>
                <p class="kas-help">Only used with streamed audio. Blank uses server defaults; unsupported options produce a visible error.</p>
                <label class="kas-field">Transport <select id="kas-transport"><option value="">Launcher default</option><option value="sse">SSE audio events</option><option value="audio">Raw HTTP PCM/WAV</option></select></label>
                <label class="kas-field">Chunk policy <select id="kas-policy"><option value="">Server default</option><option>grow</option><option>fixed</option></select></label>
                <div class="kas-grid">
                    <label class="kas-field">Frames per event <input id="kas-frames" type="number" min="1" placeholder="Server default"></label>
                    <label class="kas-field">Lookahead frames <input id="kas-lookahead" type="number" min="0" placeholder="Server default"></label>
                </div>
            </fieldset>
        </div>
        <footer class="kas-footer">
            <button id="kas-stop" type="button">Stop speech</button>
            <p id="kas-status" aria-live="polite">Ready. Select OpenAI-Compatible API Server in Media.</p>
        </footer>`;
    document.body.append(panel);
    const menuItem = document.createElement('li');
    menuItem.className = 'nav-item';
    const menuButton = document.createElement('button');
    menuButton.type = 'button';
    menuButton.className = 'nav-link mainnav';
    menuButton.textContent = 'Audio Streaming';
    menuButton.onclick = () => { closeTopNav(); panel.hidden = !panel.hidden; };
    menuItem.append(menuButton);
    document.querySelector('#topmenu ul').append(menuItem);
    panel.querySelector('#kas-close').onclick = () => { panel.hidden = true; };
    const controls = [...panel.querySelectorAll('input,select')];
    for (const [id, key] of [['kas-enabled', 'streaming_enabled'], ['kas-buffer', 'playback_buffer_ms'],
        ['kas-rate', 'pcm_sample_rate'], ['kas-text-mode', 'text_mode'], ['kas-text-limit', 'text_limit'],
        ['kas-tone-tags', 'tone_tags_supported'],
        ['kas-policy', 'stream_chunk_policy'], ['kas-frames', 'stream_frames_per_event'],
        ['kas-lookahead', 'stream_lookahead_margin']]) {
        const control = panel.querySelector('#' + id);
        if (control.type === 'checkbox') control.checked = id === 'kas-tone-tags' ? false : settings[key];
        else control.value = settings[key] ?? '';
    }
    panel.querySelector('#kas-transport').title = `Launcher default: ${settings.transport === 'sse' ? 'SSE' : 'Raw PCM'}`;
    try {
        const saved = JSON.parse(localStorage.getItem('kobold-audio-streaming') || '{}');
        if (saved.text_mode_default_version === 2 && saved['kas-text-mode'] === 'whole') {
            saved['kas-text-mode'] = 'narration';
        }
        if (saved.text_mode_default_version !== 3) {
            saved.text_mode_default_version = 3;
            localStorage.setItem('kobold-audio-streaming', JSON.stringify(saved));
        }
        for (const control of controls) if (saved[control.id] !== undefined) {
            if (control.type === 'checkbox') control.checked = saved[control.id];
            else control.value = saved[control.id];
        }
    } catch (error) { console.warn('[kobold-audio-stream] settings:', error); }
    function updateControls() {
        const streaming = panel.querySelector('#kas-enabled').checked;
        const mode = panel.querySelector('#kas-text-mode').value;
        const toneTags = panel.querySelector('#kas-tone-tags');
        const toneAvailable = settings.tone_tags_supported === true;
        panel.querySelector('#kas-text-mode').disabled = !streaming;
        panel.querySelector('#kas-text-limit').disabled = !streaming || panel.querySelector('#kas-text-mode').value !== 'bounded';
        toneTags.disabled = !streaming || !toneAvailable || !['narration', 'sentences'].includes(mode);
        panel.querySelector('#kas-tone-help').textContent = !streaming
            ? 'Requires Stream OpenAI TTS audio.'
            : !toneAvailable
            ? 'Tone tags are available with Breeze 2.'
            : mode === 'narration'
                ? "Optional. With Media's Narration streaming on, tags set each sentence's instruction; otherwise the first tag applies to the full reply."
                : mode === 'sentences'
                    ? 'Optional. Each sentence gets its tagged instruction.'
                    : 'Optional. Requires Follow narration or Separate sentences mode.';
        for (const id of ['buffer', 'rate', 'transport', 'policy', 'frames', 'lookahead']) {
            panel.querySelector('#kas-' + id).disabled = !streaming;
        }
    }
    updateControls();
    panel.addEventListener('change', () => {
        updateControls();
        const saved = Object.fromEntries(controls.map(control => [control.id, control.type === 'checkbox' ? control.checked : control.value]));
        saved.text_mode_default_version = 3;
        try { localStorage.setItem('kobold-audio-streaming', JSON.stringify(saved)); }
        catch (error) { console.warn('[kobold-audio-stream] settings:', error); }
    });
    const status = panel.querySelector('#kas-status');
    const tonePattern = /\[(?:Tone|Mood|Instruction|Voice):\s*([^\]]+)\]/gi;
    function toneTagsEnabled() {
        return settings.tone_tags_supported === true && panel.querySelector('#kas-tone-tags').checked
            && ['narration', 'sentences'].includes(panel.querySelector('#kas-text-mode').value);
    }
    function useTextQueue(originalNarrationStreaming) {
        const mode = panel.querySelector('#kas-text-mode').value;
        if (mode === 'whole') return false;
        return mode === 'narration' ? originalNarrationStreaming : true;
    }
    function toneInstruction(text) {
        if (!toneTagsEnabled()) return null;
        return [...text.matchAll(tonePattern)][0]?.[1].trim() ?? null;
    }
    function chunkText(text) {
        if (!toneTagsEnabled()) text = text.replace(tonePattern, '');
        const mode = panel.querySelector('#kas-text-mode').value;
        if (mode === 'whole') return [text.trim()].filter(Boolean);
        const blocks = [];
        let tag = '';
        let start = 0;
        for (const match of text.matchAll(tonePattern)) {
            const content = text.slice(start, match.index).trim();
            if (content) blocks.push({tag, content});
            tag = match[0];
            start = match.index + match[0].length;
        }
        const tail = text.slice(start).trim();
        if (tail) blocks.push({tag, content: tail});
        const chunks = [];
        for (const {tag, content} of blocks) {
            const prefix = tag ? tag + ' ' : '';
            if (mode === 'narration' || mode === 'narration_on') {
                const originalChunks = content.replaceAll('. ', '.\n').replaceAll('! ', '!\n').replaceAll('? ', '?\n')
                    .split('\n').map(chunk => chunk.trim()).filter(Boolean);
                chunks.push(...originalChunks.map(chunk => prefix + chunk));
                continue;
            }
            const sentences = [...new Intl.Segmenter(undefined, {granularity: 'sentence'}).segment(content)]
                .map(item => item.segment.trim()).filter(Boolean);
            if (mode === 'sentences') { chunks.push(...sentences.map(sentence => prefix + sentence)); continue; }
            const limit = Math.max(80, Number(panel.querySelector('#kas-text-limit').value) || settings.text_limit);
            let current = '';
            for (const sentence of sentences) for (const word of sentence.split(/\s+/)) {
                if (current && prefix.length + current.length + word.length + 1 > limit) {
                    chunks.push(prefix + current); current = '';
                }
                current += (current ? ' ' : '') + word;
            }
            if (current) chunks.push(prefix + current);
        }
        return chunks;
    }

    function stop() {
        window.koboldAudioPlayback.stop();
        status.textContent = 'Speech stopped';
    }
    panel.querySelector('#kas-stop').onclick = stop;
    panel.querySelector('#kas-enabled').onchange = stop;

    function speechEndpoint(url) {
        // Route this PC's audio proxy through Lite's origin for remote/mobile clients.
        const endpoint = new URL(url, location.href);
        if (['localhost', '127.0.0.1'].includes(endpoint.hostname) &&
            endpoint.port === String(settings.audioProxyPort) && endpoint.pathname === '/v1/audio/speech') {
            return new URL('/v1/audio/speech', location.href).href;
        }
        return url;
    }

    async function speak(url, payload, headers, download, embed) {
        const options = {...payload.options};
        for (const [id, key] of [['kas-policy', 'stream_chunk_policy'], ['kas-frames', 'stream_frames_per_event'], ['kas-lookahead', 'stream_lookahead_margin']]) {
            const value = panel.querySelector('#' + id).value.trim();
            if (value) options[key] = id === 'kas-policy' ? value : Number(value);
        }
        status.textContent = 'Generating speech...';
        const bufferSeconds = Math.max(0, Number(panel.querySelector('#kas-buffer').value)) / 1000;
        const onProgress = stats => {
            status.textContent = `First data ${stats.first.toFixed(2)}s | ${stats.chunks} chunks | ${stats.underruns} underruns | buffer ${bufferSeconds}s`;
        };
        await window.koboldAudioPlayback.speak(speechEndpoint(url), {...payload, options}, headers, download, embed, {
            bufferSeconds, rate: Number(panel.querySelector('#kas-rate').value),
            transport: panel.querySelector('#kas-transport').value || settings.transport || 'audio',
            onProgress, onComplete: () => { status.textContent += ' | generation complete'; },
            onError: error => { status.textContent = `Speech error: ${error.message}`; console.error('[kobold-audio-stream]', error); },
        });
    }
    window.koboldAudioStream = {enabled: () => panel.querySelector('#kas-enabled').checked, speak, stop, chunkText, toneInstruction, speechEndpoint, useTextQueue};
})();

