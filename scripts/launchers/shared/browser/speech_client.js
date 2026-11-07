/* Same-origin speech API transport. UI adapters own presentation and capture policy. */
(() => {
    class SpeechClient {
        policy = null;
        constructor(endpoint = '/v1/audio/speech') { this.endpoint = endpoint; }
        async prepare() {
            this.context ||= new AudioContext();
            this.player ||= new PcmAudio.Player(this.context);
            await this.context.resume();
        }
        stop() { this.player?.stop(); this.cancelPlayback?.(); }
        async json(path, body, signal, binary = false) {
            const response = await SpeechTools.checked(await fetch(path, {
                method: 'POST', signal,
                headers: {'Content-Type': binary ? 'application/octet-stream' : 'application/json'},
                body: binary ? body : JSON.stringify(body)
            }));
            return response.json();
        }
        live(path, body, json = false, signal) {
            return this.json(`/asr/live/${path}`, body, signal, !json);
        }
        async transcribe(blob, language, signal) {
            const body = new FormData(); body.append('file', blob, 'speech.wav');
            body.append('language', language); body.append('response_format', 'json');
            return (await SpeechTools.checked(await fetch('/v1/audio/transcriptions', {
                method: 'POST', body, signal
            }))).json();
        }
        async synthesize(text, profile, signal) {
            return (await SpeechTools.checked(await fetch(this.endpoint, {
                method: 'POST', signal, headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({input: text, voice: profile.voice,
                    options: {language: profile.locale}, response_format: 'wav', stream: false})
            }))).blob();
        }
        async chatResponse(input, options, transport = fetch, adapt = true) {
            const payload = JSON.parse(options.body || '{}'), wantedStream = !!payload.stream;
            payload.stream = this.policy?.llm?.mode !== 'whole';
            let response = await transport(input, {...options, body: JSON.stringify(payload)});
            if (payload.stream && await unsupported(response)) {
                payload.stream = false;
                response = await transport(input, {...options, body: JSON.stringify(payload)});
            }
            const streamed = response.headers?.get('content-type')?.includes('text/event-stream');
            this.lastChatMode = streamed ? 'streaming' : 'whole';
            if (adapt && wantedStream && response.ok && !streamed) {
                const data = await response.json(), content = data.choices?.[0]?.message?.content || '';
                const chunk = {...data, choices: [{index: 0, delta: {content}, finish_reason: data.choices?.[0]?.finish_reason || 'stop'}]};
                return new Response(`data: ${JSON.stringify(chunk)}\n\ndata: [DONE]\n\n`, {
                    headers: {'Content-Type': 'text/event-stream'}
                });
            }
            return response;
        }
        async chat(payload, signal, onText) {
            const response = await this.chatResponse('/v1/chat/completions', {method: 'POST', signal,
                headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...payload, stream: true})}, fetch, false);
            await SpeechTools.checked(response);
            return assistantText(response, signal, onText);
        }
        async audioResponse(text, profile, stream, signal, extra = {}) {
            return fetch(this.endpoint, {method: 'POST', signal, headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({...extra, input: text, voice: extra.voice || profile.voice,
                    options: {language: profile.locale, ...extra.options}, stream,
                    stream_format: stream ? 'audio' : undefined, response_format: stream ? 'pcm' : 'wav'})});
        }
        async whole(blob, signal, element) {
            const audio = element || (this.audio ||= new Audio()), url = URL.createObjectURL(blob);
            audio.src = url;
            let finish, fail;
            const ended = new Promise((resolve, reject) => {
                finish = () => resolve();
                fail = () => reject(new Error('Audio playback failed'));
                if (audio.addEventListener) {
                    audio.addEventListener('ended', finish, {once: true}); audio.addEventListener('error', fail, {once: true});
                } else { audio.onended = finish; audio.onerror = fail; }
            });
            const cancel = () => { audio.pause(); finish(); };
            this.cancelPlayback = cancel; signal?.addEventListener('abort', cancel, {once: true});
            try { signal?.throwIfAborted(); await audio.play(); await ended; signal?.throwIfAborted(); }
            finally {
                signal?.removeEventListener('abort', cancel); this.cancelPlayback = null;
                audio.removeEventListener?.('ended', finish); audio.removeEventListener?.('error', fail);
                URL.revokeObjectURL(url);
            }
        }
        async say(text, profile, signal, options = {}) {
            signal?.throwIfAborted();
            const plan = this.policy?.tts || {mode: 'whole', supported: ['whole']};
            let mode = options.mode && options.mode !== 'auto' ? options.mode : plan.mode;
            if (mode === 'stream') mode = 'streaming';
            if (mode === 'buffered') mode = 'whole';
            if (mode === 'streaming' && !plan.supported?.includes('streaming')) mode = 'chunked';
            let response;
            if (mode === 'streaming') {
                response = await this.audioResponse(text, profile, true, signal, options.payload);
                if (await unsupported(response)) mode = 'chunked';
                else {
                    await SpeechTools.checked(response); await this.prepare(); options.onMode?.('streaming');
                    try {
                        await this.player.consume(response, {signal, rate: plan.pcm_sample_rate,
                            bufferSeconds: (plan.playback_buffer_ms ?? 300) / 1000, rawPcm: true});
                    } catch (error) {
                        if (error.code !== 'EMPTY_AUDIO_STREAM') throw error;
                        signal?.throwIfAborted();
                        options.onMode?.('complete fallback · empty audio stream');
                        response = await this.audioResponse(text, profile, false, signal, options.payload);
                        await SpeechTools.checked(response);
                        await this.whole(await response.blob(), signal, options.audio);
                        return;
                    }
                    await this.drain(signal); return;
                }
            }
            options.onMode?.(mode);
            const parts = mode === 'chunked' ? splitSpeech(text, true).parts : [text];
            for (const [index, part] of parts.entries()) {
                signal?.throwIfAborted();
                response = await this.audioResponse(part, profile, false, signal, options.payload);
                if (mode === 'chunked' && index === 0 && await unsupported(response)) {
                    return this.say(text, profile, signal, {...options, mode: 'whole'});
                }
                await SpeechTools.checked(response);
                await this.whole(await response.blob(), signal, options.audio);
            }
        }
        async drain(signal) {
            while (this.player.sources.size) {
                signal?.throwIfAborted(); await new Promise(resolve => setTimeout(resolve, 40));
            }
            signal?.throwIfAborted();
        }
        utterance(profile, signal, options = {}) {
            let pending = '', queue = Promise.resolve(), failed;
            const fullReply = options.textMode === 'full_reply';
            const enqueue = text => {
                queue = queue.then(() => { if (failed) return; return this.say(text, profile, signal, options); })
                    .catch(error => { failed = error; if (error.name !== 'AbortError' && !signal?.aborted) this.stop(); });
            };
            const release = final => {
                if (fullReply && !final) return;
                const selected = options.mode && options.mode !== 'auto' ? options.mode : this.policy?.tts?.mode || 'whole';
                const whole = fullReply || ['whole', 'buffered'].includes(selected);
                if (whole && !final) return;
                const value = whole ? {parts: [pending], rest: ''} : splitSpeech(pending, final);
                pending = value.rest; value.parts.filter(part => part.trim()).forEach(enqueue);
            };
            return {
                feed: text => { pending += text; release(false); },
                finish: async () => { release(true); await queue; if (failed) throw failed; }
            };
        }
    }
    async function unsupported(response) {
        if (response.ok) return false;
        if ([404, 405, 415, 501].includes(response.status)) return true;
        if (![400, 422].includes(response.status)) return false;
        const message = await response.clone().text();
        return /stream|pcm|format/i.test(message) && /unsupported|not supported|unknown|invalid/i.test(message);
    }
    function splitSpeech(text, final = false) {
        const parts = []; let rest = text;
        while (rest) {
            const sentence = rest.match(/^[\s\S]*?[.!?。！？](?:\s|$)/u);
            let length = sentence?.[0].length || 0;
            if (!length && rest.length > 320) length = Math.max(120, rest.lastIndexOf(' ', 320));
            if (!length) break;
            parts.push(rest.slice(0, length)); rest = rest.slice(length);
        }
        if (final && rest.trim()) { parts.push(rest); rest = ''; }
        return {parts, rest};
    }
    // Observe a cloned chat response without consuming or changing the UI's stream.
    async function assistantText(response, signal, onText) {
        if (!response.headers?.get('content-type')?.includes('text/event-stream')) {
            const data = await response.json(); signal?.throwIfAborted();
            const text = data.choices?.[0]?.message?.content || ''; onText?.(text); return text;
        }
        const reader = response.body.getReader(), decoder = new TextDecoder();
        let pending = '', text = '', completed = false;
        const cancel = () => { void reader.cancel().catch(() => {}); };
        signal?.addEventListener('abort', cancel, {once: true});
        try {
            while (!completed) {
                const {value, done} = await reader.read(); signal?.throwIfAborted();
                pending += decoder.decode(value, {stream: !done});
                const lines = pending.split('\n'); pending = done ? '' : lines.pop();
                for (const line of lines) {
                    if (!line.startsWith('data:')) continue;
                    const raw = line.slice(5).trim();
                    if (raw === '[DONE]') { completed = true; break; }
                    if (!raw) continue;
                    const data = JSON.parse(raw);
                    if (data.error) throw new Error(data.error.message || 'Chat stream failed');
                    const choice = data.choices?.[0];
                    if (typeof choice?.delta?.content === 'string' && choice.finish_reason !== 'tool_calls') {
                        text += choice.delta.content; onText?.(choice.delta.content);
                    }
                    if (choice?.finish_reason === 'tool_calls') { text = ''; completed = true; }
                    if (choice?.finish_reason === 'stop') completed = true;
                }
                if (text.length + pending.length > 1048576) throw new Error('Speech reply exceeds 1 MiB');
                if (done) break;
            }
            if (!completed) throw new Error('Chat ended before completion; speech skipped');
            return text;
        } finally {
            signal?.removeEventListener('abort', cancel); cancel();
        }
    }
    globalThis.SpeechClient = SpeechClient;
    globalThis.SpeechAssistantText = assistantText;
})();
