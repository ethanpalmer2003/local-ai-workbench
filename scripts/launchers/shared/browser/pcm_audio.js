/* Shared PCM16 playback. UI and backend-specific request options belong to callers. */
(() => {
    const concat = (a, b) => { const bytes = new Uint8Array(a.length + b.length); bytes.set(a); bytes.set(b, a.length); return bytes; };
    const label = bytes => String.fromCharCode(...bytes);
    const aborted = () => Object.assign(new Error('Speech stopped'), {name: 'AbortError'});

    function wav(parts, rate, channels = 1) {
        const length = parts.reduce((sum, part) => sum + part.length, 0);
        const bytes = new Uint8Array(44 + length);
        const view = new DataView(bytes.buffer);
        const text = (at, value) => [...value].forEach((c, i) => view.setUint8(at + i, c.charCodeAt(0)));
        text(0, 'RIFF'); view.setUint32(4, 36 + length, true); text(8, 'WAVEfmt ');
        view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, channels, true);
        view.setUint32(24, rate, true); view.setUint32(28, rate * 2 * channels, true);
        view.setUint16(32, 2 * channels, true); view.setUint16(34, 16, true);
        text(36, 'data'); view.setUint32(40, length, true);
        let at = 44;
        for (const part of parts) { bytes.set(part, at); at += part.length; }
        return bytes.buffer;
    }

    class SseTransport {
        constructor(sink) { this.sink = sink; this.decoder = new TextDecoder(); this.pending = ''; this.done = false; }
        event(block) {
            const data = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trimStart()).join('\n');
            if (!data) return;
            if (data === '[DONE]') { this.done = true; return; }
            const message = JSON.parse(data);
            if (message.error || message.type === 'error') throw new Error(JSON.stringify(message));
            if (message.type === 'speech.audio.done') { this.done = true; return; }
            if (message.type !== 'speech.audio.delta') return;
            if (this.done) throw new Error('Audio received after completion');
            this.sink.pcm(Uint8Array.from(atob(message.audio), c => c.charCodeAt(0)));
        }
        feed(bytes, done = false) {
            this.pending = (this.pending + this.decoder.decode(bytes, {stream: !done})).replace(/\r\n/g, '\n');
            let boundary;
            while ((boundary = this.pending.indexOf('\n\n')) >= 0) {
                this.event(this.pending.slice(0, boundary)); this.pending = this.pending.slice(boundary + 2);
            }
            if (done && this.pending.trim()) { this.event(this.pending); this.pending = ''; }
        }
        finish() {
            this.feed(undefined, true);
            if (!this.done) throw new Error('Audio stream ended without completion marker');
        }
    }

    class HttpTransport {
        constructor(sink, expectWav) {
            this.sink = sink; this.expectWav = expectWav; this.header = new Uint8Array();
            this.offset = 12; this.format = false; this.remaining = Infinity;
        }
        formatChunk(bytes) {
            const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
            const tag = view.getUint16(0, true);
            const channels = view.getUint16(2, true), rate = view.getUint32(4, true);
            const pcmGuid = [1, 0, 0, 0, 0, 0, 16, 0, 128, 0, 0, 170, 0, 56, 155, 113];
            const extensiblePcm = tag === 65534 && bytes.length >= 40 && view.getUint16(16, true) >= 22 &&
                view.getUint16(18, true) === 16 && pcmGuid.every((value, i) => bytes[24 + i] === value);
            if ((tag !== 1 && !extensiblePcm) || view.getUint16(14, true) !== 16 ||
                !channels || !rate || view.getUint16(12, true) !== channels * 2) throw new Error('WAV requires 16-bit PCM');
            this.sink.rate = rate; this.sink.channels = channels; this.format = true;
        }
        audio(bytes) {
            const count = Math.min(bytes.length, this.remaining);
            this.sink.pcm(bytes.subarray(0, count)); this.remaining -= count;
        }
        feed(bytes) {
            if (this.header === null) { this.audio(bytes); return; }
            this.header = concat(this.header, bytes);
            if (this.header.length < 4) return;
            if (label(this.header.subarray(0, 4)) !== 'RIFF') {
                if (this.expectWav) throw new Error('Invalid WAV header');
                const raw = this.header; this.header = null; this.audio(raw); return;
            }
            if (this.header.length < 12) return;
            if (label(this.header.subarray(8, 12)) !== 'WAVE') throw new Error('Invalid WAV stream');
            const view = new DataView(this.header.buffer);
            while (this.offset + 8 <= this.header.length) {
                const at = this.offset, name = label(this.header.subarray(at, at + 4)), size = view.getUint32(at + 4, true);
                if (name === 'data') {
                    if (!this.format) throw new Error('WAV data precedes format');
                    this.remaining = size === 0 || size === 0xffffffff ? Infinity : size;
                    const raw = this.header.subarray(at + 8); this.header = null; this.audio(raw); return;
                }
                if (at + 8 + size > 65536) throw new Error('WAV header exceeds 64 KiB');
                if (at + 8 + size > this.header.length) return;
                if (name === 'fmt ') {
                    if (size < 16) throw new Error('Incomplete WAV format');
                    this.formatChunk(this.header.subarray(at + 8, at + 8 + size));
                }
                this.offset += 8 + size + size % 2;
                if (this.offset > 65536) throw new Error('WAV header exceeds 64 KiB');
            }
        }
        finish() {
            if (this.header !== null && this.header.length && !this.expectWav &&
                label(this.header.subarray(0, 4)) !== 'RIFF') {
                const raw = this.header; this.header = null; this.audio(raw);
            }
            if (this.header !== null) throw new Error('Incomplete audio header');
            if (Number.isFinite(this.remaining) && this.remaining) throw new Error('Truncated WAV data');
        }
    }

    class RawPcmTransport {
        constructor(sink) { this.sink = sink; }
        feed(bytes) { this.sink.pcm(bytes); }
        finish() {}
    }

    class PcmSink {
        constructor(player, config) {
            this.player = player; this.config = config; this.epoch = player.epoch;
            this.rate = config.rate ?? 24000; this.channels = 1; this.carry = new Uint8Array(); this.parts = [];
            this.stats = {chunks: 0, duration: 0, underruns: 0, lateSeconds: 0, arrivals: [], first: null};
        }
        check() { if (this.epoch !== this.player.epoch || this.config.signal?.aborted) throw aborted(); }
        pcm(chunk) {
            this.check();
            const bytes = concat(this.carry, chunk), usable = bytes.length - bytes.length % (2 * this.channels);
            this.carry = bytes.slice(usable);
            if (!usable) return;
            const pcm = bytes.subarray(0, usable), frames = usable / (2 * this.channels);
            if (this.config.capture) this.parts.push(pcm);
            const buffer = this.player.context.createBuffer(this.channels, frames, this.rate);
            const view = new DataView(pcm.buffer, pcm.byteOffset, pcm.byteLength);
            for (let ch = 0; ch < this.channels; ch++) {
                const samples = buffer.getChannelData(ch);
                for (let i = 0; i < frames; i++) samples[i] = view.getInt16((i * this.channels + ch) * 2, true) / 32768;
            }
            this.schedule(buffer);
        }
        schedule(buffer) {
            this.check();
            const stats = this.stats, now = this.player.context.currentTime;
            const delay = this.config.bufferSeconds ?? 0.3;
            if (!stats.chunks) this.player.endTime = Math.max(this.player.endTime, now + delay + 0.02);
            else if (this.player.endTime < now + 0.01) {
                stats.underruns++; stats.lateSeconds += Math.max(0, now - this.player.endTime);
                this.player.endTime = now + delay + 0.02;
            }
            const elapsed = (performance.now() - this.config.started) / 1000;
            stats.arrivals.push({chunk: stats.chunks + 1, arrived_s: elapsed, audio_s: buffer.duration, queued_s: this.player.endTime - now});
            this.player.playBuffer(buffer, this.player.endTime);
            stats.chunks++; stats.duration += buffer.duration; stats.first ??= elapsed;
            this.config.onProgress?.(stats);
        }
        finish() {
            this.check();
            if (!this.stats.chunks) {
                const error = new Error(this.carry.length ? 'Incomplete PCM frame' : 'No audio received');
                error.code = 'EMPTY_AUDIO_STREAM';
                throw error;
            }
            if (this.carry.length) throw new Error('Incomplete PCM frame');
            return {...this.stats, recording: this.config.capture ? wav(this.parts, this.rate, this.channels) : null, recordingType: 'audio/wav'};
        }
    }

    class Player {
        constructor(context, destination = context.destination, onState = () => {}) {
            this.context = context; this.destination = destination; this.onState = onState;
            this.sources = new Set(); this.endTime = 0; this.epoch = 0;
        }
        stop() {
            this.epoch++;
            for (const source of this.sources) source.stop();
            this.sources.clear(); this.endTime = 0; this.onState();
        }
        playBuffer(buffer, at = Math.max(this.endTime, this.context.currentTime + 0.02)) {
            const source = this.context.createBufferSource(); source.buffer = buffer; source.connect(this.destination);
            source.onended = () => { this.sources.delete(source); this.onState(); };
            this.sources.add(source); source.start(at); this.endTime = at + buffer.duration; this.onState();
        }
        async consume(response, config = {}) {
            const sink = new PcmSink(this, {started: performance.now(), ...config});
            const type = (response.headers.get('Content-Type') || '').toLowerCase().split(';')[0].trim();
            if (/^audio\/(mpeg|mp3|ogg|opus|aac|mp4|flac|webm)$/.test(type)) {
                const bytes = await response.arrayBuffer(); sink.check();
                const decoded = await this.context.decodeAudioData(bytes.slice(0)); sink.check(); sink.schedule(decoded);
                return {...sink.stats, recording: config.capture ? bytes : null, recordingType: type};
            }
            const sse = type === 'text/event-stream';
            if (!sse && !['', 'application/octet-stream', 'audio/pcm', 'audio/x-pcm', 'audio/wav', 'audio/x-wav', 'audio/wave'].includes(type))
                throw new Error(`Unsupported streamed audio Content-Type: ${type}`);
            const transport = sse ? new SseTransport(sink)
                : config.rawPcm ? new RawPcmTransport(sink) : new HttpTransport(sink, type.includes('wav'));
            const reader = response.body.getReader();
            const cancel = () => { reader.cancel().catch(() => {}); };
            config.signal?.addEventListener('abort', cancel, {once: true});
            try {
                while (true) {
                    sink.check(); const {value, done} = await reader.read(); sink.check();
                    if (value?.length) transport.feed(value);
                    if (done) break;
                }
                transport.finish(); return sink.finish();
            } finally {
                config.signal?.removeEventListener('abort', cancel);
                await reader.cancel().catch(() => {}); reader.releaseLock();
            }
        }
    }

    function request(payload, transport = 'audio') {
        return {...payload, stream: true, stream_format: transport, response_format: 'pcm'};
    }
    globalThis.PcmAudio = {Player, wav, request};
})();
