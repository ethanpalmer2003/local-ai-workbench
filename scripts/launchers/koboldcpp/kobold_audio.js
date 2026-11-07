/* Lite lifecycle integration shared by the local panel and the single-toggle patch. */
(() => {
    let player;
    let epoch = 0;
    const requests = new Set();
    function updateBusy() {
        tts_is_processing = requests.size > 0;
        tts_is_playing = (player?.sources.size ?? 0) > 0;
        update_submit_button(false);
    }
    function stop() {
        epoch++;
        requests.forEach(controller => controller.abort()); requests.clear();
        player?.stop();
        tts_speak_input_queue = []; tts_speak_output_queue = [];
        updateBusy();
    }
    async function speak(url, payload, headers, download, embed, config = {}) {
        player ??= new PcmAudio.Player(ttsAudioContext, ttsMasterGain, updateBusy);
        player.destination = ttsMasterGain;
        const ticket = epoch, controller = new AbortController();
        requests.add(controller); updateBusy();
        const started = performance.now();
        try {
            await ttsAudioContext.resume();
            if (ticket !== epoch) return;
            const body = PcmAudio.request(payload, config.transport ?? 'audio');
            // OpenAI's own endpoint does not accept the compatible-server stream flag.
            if (new URL(url, location.href).hostname === 'api.openai.com') delete body.stream;
            const response = await fetch(url, {method: 'POST', headers, body: JSON.stringify(body), signal: controller.signal});
            if (ticket !== epoch) { await response.body?.cancel(); return; }
            if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
            const result = await player.consume(response, {...config, started, signal: controller.signal, capture: download || embed});
            if (ticket !== epoch) return;
            if (download && result.recording) tts_download(result.recording);
            if (embed && result.recording) tts_embed_audio(result.recording);
            config.onComplete?.(result);
        } catch (error) {
            if (ticket === epoch && error.name !== 'AbortError') {
                if (config.onError) config.onError(error);
                else { console.error('[tts-stream]', error); msgbox('TTS Stream Error: ' + error.message); }
            }
        } finally { requests.delete(controller); updateBusy(); }
    }
    window.addEventListener('beforeunload', stop);
    window.koboldAudioPlayback = {speak, stop};
})();
