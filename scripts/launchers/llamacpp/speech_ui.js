/* Native llama-ui adapter. All model, VAD and text-cleanup policy stays in the gateway. */
(() => {
    // Keep native new-chat navigation reloadable without replacing the workspace's root route.
    for (const method of ['pushState', 'replaceState']) {
        const original = history[method].bind(history);
        history[method] = (data, unused, value) => {
            if (value != null) {
                const url = new URL(value, location.href);
                if (url.origin === location.origin && url.pathname === '/') url.searchParams.set('ui', 'llama');
                value = url.href;
            }
            return original(data, unused, value);
        };
    }
    const api = new SpeechClient(), originalFetch = globalThis.fetch.bind(globalThis);
    let selectedLanguage = '', listener, transcriptHandler, ready = false, message = '', profiles = {}, serverStatus;
    let media, context, source, recorder, session, timer, frames = [], uploading = false;
    let capturing = false, starting = false, chatBusy = false, speaking = false, captureEpoch = 0;
    let generation = 0, chatEpoch = 0, speechAbort;
    const snapshot = () => ({ready, recording: capturing || starting, speaking, status: message});
    const notify = () => listener?.(snapshot());
    const status = text => { message = text; notify(); };
    const profile = () => profiles[selectedLanguage];
    function speechStartMode() {
        try {
            return JSON.parse(localStorage.getItem('speech-workspace.preferences.v1') || '{}').speechStart === 'full_reply'
                ? 'full_reply' : 'sentence';
        } catch (_) { return 'sentence'; }
    }
    function refreshMic() { notify(); }
    function stopSpeech() {
        generation++; speechAbort?.abort(); api.stop(); speaking = false; notify();
    }
    // Observe only user conversation streams, excluding native title generation and prefill requests.
    globalThis.fetch = async (input, options = {}) => {
        const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url, location.href);
        const headers = new Headers(options.headers || (input instanceof Request ? input.headers : undefined));
        const observed = url.origin === location.origin && /\/v1\/chat\/completions$/.test(url.pathname)
            && headers.has('X-Conversation-Id');
        if (!observed) return originalFetch(input, options);
        stopSpeech(); const epoch = generation, requestEpoch = ++chatEpoch; chatBusy = true;
        speechAbort = new AbortController();
        const spoken = ready ? api.utterance(profile(), speechAbort.signal,
            {textMode: speechStartMode(), onMode: mode => { if (epoch === generation) { speaking = true; status(`Speaking (${mode})`); } }}) : null;
        try {
            const response = await api.chatResponse(input, options, originalFetch);
            if (!response.ok) { if (requestEpoch === chatEpoch) chatBusy = false; return response; }
            void SpeechAssistantText(response.clone(), options.signal, delta => spoken?.feed(delta)).then(async () => {
                if (requestEpoch === chatEpoch) chatBusy = false;
                if (epoch !== generation) return;
                await spoken?.finish();
                if (epoch === generation) { speaking = false; status(''); }
            }).catch(error => {
                if (requestEpoch === chatEpoch) chatBusy = false;
                if (epoch === generation) { speechAbort.abort(); api.stop(); speaking = false; if (error.name !== 'AbortError') status(error.message); else notify(); }
            });
            return response;
        } catch (error) { if (requestEpoch === chatEpoch) chatBusy = false; throw error; }
    };
    async function insertTranscript(text) {
        if (!text?.trim() || chatBusy || speaking) return;
        if (!transcriptHandler) throw new Error('Native chat editor is not ready');
        await transcriptHandler(text.trim());
    }
    async function flush() {
        if (uploading || !session || !capturing) return;
        uploading = true; const token = session;
        try {
            const batch = frames.splice(0), pcm = new ArrayBuffer(batch.length * 1024), view = new DataView(pcm);
            batch.forEach((frame, n) => frame.forEach((v, i) => view.setInt16(n * 1024 + i * 2,
                Math.max(-1, Math.min(1, v)) * 32767, true)));
            const value = await api.live(`${token}/audio`, pcm);
            if (token !== session) return;
            for (const event of value.events || []) {
                if (event.type === 'transcript.text.done') await insertTranscript(event.text || event.transcript);
            }
        } catch (error) { if (token === session) { await stopCapture(false); status(error.message); } }
        finally { uploading = false; }
    }
    async function stopCapture(transcribe = true) {
        captureEpoch++; capturing = starting = false; clearInterval(timer);
        const token = session; session = null;
        const recorded = frames.splice(0);
        recorder?.disconnect(); source?.disconnect(); media?.getTracks().forEach(track => track.stop());
        await context?.close(); context = null; refreshMic();
        if (token) await api.live(`${token}/stop`, new ArrayBuffer(0));
        else if (transcribe && recorded.length) {
            status('Transcribing...');
            const samples = new Float32Array(recorded.length * 512);
            recorded.forEach((frame, n) => samples.set(frame, n * 512));
            const result = await api.transcribe(SpeechTools.wav(samples, 16000), profile().asr_language);
            await insertTranscript(result.text);
        }
    }
    async function startCapture() {
        const epoch = ++captureEpoch; starting = true; refreshMic(); status('Preparing microphone...');
        try {
            const stream = await navigator.mediaDevices.getUserMedia({audio: {channelCount: 1, echoCancellation: true, noiseSuppression: true}});
            if (epoch !== captureEpoch) { stream.getTracks().forEach(track => track.stop()); return; }
            media = stream; context = new AudioContext({sampleRate: 16000});
            if (context.sampleRate !== 16000) throw new Error('Microphone requires 16 kHz capture');
            await context.audioWorklet.addModule('/practice-worklet.js');
            source = context.createMediaStreamSource(media); recorder = new AudioWorkletNode(context, 'practice-microphone');
            if (serverStatus.automatic_turns) {
                const result = await api.live('start', {language: profile().asr_language}, true);
                if (epoch !== captureEpoch) { await api.live(`${result.session}/stop`, new ArrayBuffer(0)); return; }
                session = result.session;
            }
            if (epoch !== captureEpoch) return;
            frames = []; capturing = true; starting = false;
            recorder.port.onmessage = event => {
                if (!capturing) return;
                if (frames.length >= (session ? 28 : 937)) {
                    void stopCapture(!session).catch(error => status(error.message)); return;
                }
                frames.push(chatBusy || speaking ? new Float32Array(512) : event.data);
            };
            source.connect(recorder); recorder.connect(context.destination); await context.resume();
            if (session) timer = setInterval(flush, 128);
            refreshMic(); status(session ? 'Listening' : 'Recording - stop to transcribe');
        } catch (error) {
            if (epoch === captureEpoch) { await stopCapture(false); status(error.message); }
        }
    }
    async function configure() {
        try {
            serverStatus = await (await SpeechTools.checked(await originalFetch('/asr/status'))).json();
            api.policy = serverStatus.delivery || null;
            const common = serverStatus.languages.common.filter(row => row.available !== false);
            profiles = Object.fromEntries(common.map(row => [row.locale, row]));
            let saved;
            try { saved = JSON.parse(localStorage.getItem('speech-workspace.preferences.v1') || '{}').language; } catch (_) {}
            selectedLanguage = profiles[saved] ? saved : common.find(row => row.code === 'fr')?.locale || common[0]?.locale || '';
            ready = !!selectedLanguage;
            status(ready ? '' : 'ASR and TTS have no common language. Change models in /test/.');
        } catch (error) { ready = false; status(error.message); }
    }
    globalThis.WorkspaceSpeech = {
        bind(onTranscript, onState) {
            transcriptHandler = onTranscript; listener = onState; notify();
            return () => {
                transcriptHandler = listener = null;
                stopSpeech(); void stopCapture(false).catch(() => {});
            };
        },
        async toggleCapture() {
            if (!ready) { status('Speech services are not ready'); return; }
            try { await (capturing || starting ? stopCapture() : startCapture()); }
            catch (error) { status(error.message); }
        },
        stop() { stopSpeech(); void stopCapture(false).catch(error => status(error.message)); },
        configure
    };
    window.addEventListener('pagehide', () => {
        stopSpeech(); clearInterval(timer); media?.getTracks().forEach(track => track.stop());
        if (session) navigator.sendBeacon(`/asr/live/${session}/stop`, new Blob([]));
    });
    void configure();
})();
