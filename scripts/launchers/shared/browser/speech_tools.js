/* Shared browser speech contracts. Keep engine and conversation policy in adapters. */
(() => {
    async function checked(response) {
        if (!response.ok) {
            const text = await response.text();
            let message = text;
            try { message = JSON.parse(text).error?.message || text; } catch (_) {}
            throw new Error(message || `HTTP ${response.status}`);
        }
        return response;
    }
    function wav(samples, rate) {
        const pcm = new Uint8Array(samples.length * 2), view = new DataView(pcm.buffer);
        samples.forEach((value, i) => view.setInt16(i * 2, Math.max(-1, Math.min(1, value)) * 32767, true));
        return new Blob([PcmAudio.wav([pcm], rate)], {type: 'audio/wav'});
    }
    async function measure(stage, operation, record) {
        const now = () => globalThis.performance?.now() ?? Date.now();
        const started = now(); let result = 'failed';
        try { const value = await operation(); result = 'complete'; return value; }
        catch (error) {
            result = error?.name === 'AbortError'
                ? 'cancelled'
                : `failed · ${error?.message || String(error)}`;
            throw error;
        }
        finally { record(stage, now() - started, result); }
    }
    function toggle(button) {
        // Preserve the existing boolean control contract; ARIA owns visible/accessibility state.
        Object.defineProperty(button, 'checked', {
            get() { return this.ariaPressed === 'true'; },
            set(value) { this.ariaPressed = String(Boolean(value)); }
        });
        button.onclick = () => {
            if (button.disabled) return;
            button.checked = !button.checked;
            return button.onchange?.();
        };
    }
    globalThis.SpeechTools = {checked, wav, measure, toggle};
})();
