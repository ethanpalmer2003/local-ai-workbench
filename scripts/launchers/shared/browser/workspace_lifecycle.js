/* Service controls for the shared workspace. No request is required to open this page. */
(() => {
    let available = false, managed = false, seen = new Set(), refreshing = false, refreshAgain = false;
    let statusRevision = 0;
    const loadingContexts = new Map();
    let timer;
    const $ = id => document.getElementById(id);
    function loading(stage, context = 'request', queued = false) {
        if (!managed) return;
        statusRevision++;
        const node = $(`residency-${stage}`);
        if (!node || (!queued && ['loaded', 'external', 'shared resident'].includes(node.dataset.state))) return;
        loadingContexts.set(stage, {context, queued});
        node.hidden = false;
        node.dataset.state = 'loading';
        const label = stage.toUpperCase();
        node.textContent = context === 'preload'
            ? `${queued ? 'Queued to preload' : 'Preloading'} ${label}...`
            : `Loading ${label} for request...`;
        $('lifecycle-note').textContent = context === 'preload'
            ? 'Preloading enabled stages...'
            : 'Loading models for request...';
    }
    async function refresh() {
        if (!managed) return;
        if (refreshing) { refreshAgain = true; return; }
        refreshing = true;
        const revision = statusRevision;
        try {
        const response = await fetch('/workspace/lifecycle', {cache: 'no-store'});
        if (revision !== statusRevision) { refreshAgain = true; return; }
        if (!response.ok) {
            $('lifecycle-note').textContent = 'Lifecycle controls unavailable.';
            $('load-active-models').disabled = true;
            $('unload-all').disabled = true;
            for (const stage of ['asr', 'tts', 'llm']) {
                const node = $(`residency-${stage}`);
                node.hidden = false;
                node.dataset.state = 'failed';
                node.textContent = `${stage.toUpperCase()} status unavailable`;
            }
            return;
        }
        const value = await response.json(); available = true;
        if (revision !== statusRevision) { refreshAgain = true; return; }
        const busy = globalThis.SpeechWorkspace?.busy() || false;
        $('load-active-models').disabled = busy;
        $('unload-all').disabled = busy;
        for (const [stage, service] of Object.entries(value.stages)) {
            const node = $(`residency-${stage}`);
            const labels = {unloaded: 'Unloaded · starts on request', loading: 'Loading model...', loaded: 'Loaded', external: 'Reused service', failed: 'Load failed', 'shared resident': 'Resident (shared)'};
            node.hidden = false;
            node.dataset.state = service.state;
            const pending = loadingContexts.get(stage);
            if (service.state === 'loading' && pending) {
                const name = stage.toUpperCase();
                node.textContent = pending.context === 'preload'
                    ? `${pending.queued ? 'Queued to preload' : 'Preloading'} ${name}...`
                    : `Loading ${name} for request...`;
            } else if (service.state === 'unloaded' && pending) {
                node.dataset.state = 'loading';
                const name = stage.toUpperCase();
                node.textContent = pending.context === 'preload'
                    ? `${pending.queued ? 'Queued to preload' : 'Preloading'} ${name}...`
                    : `Loading ${name} for request...`;
            } else {
                if (service.state !== 'loading') loadingContexts.delete(stage);
                node.textContent = `${labels[service.state] || service.state}${service.pid ? ` · PID ${service.pid}` : ''}`;
            }
        }
        $('lifecycle-note').textContent = 'Uncheck a stage to unload it. Shared servers stop when unused.';
        $('lifecycle-log').textContent = `Log: ${value.log}`;
        for (const event of value.events) {
            const key = `${event.timestamp}:${event.id}`;
            if (seen.has(key)) continue;
            seen.add(key);
            const phase = event.phase === 'startup_ready' && event.includes_model_load ? 'startup + model ready' : event.phase.replaceAll('_', ' ');
            const result = event.error ? `failed · ${event.error}` : event.outcome || (event.reused ? 'reused; load time unknown' : 'server time');
            globalThis.SpeechWorkspace?.record(`${event.stage.toUpperCase()} ${phase}`, event.duration_ms, result, event.model || 'Not recorded');
        }
        } finally {
            refreshing = false;
            if (refreshAgain) {
                refreshAgain = false;
                refresh().catch(() => {});
            }
        }
    }
    async function action(stage, operation, context = 'request') {
        if (!available) throw new Error('Service lifecycle is not ready.');
        if (operation === 'load') loading(stage, context);
        else {
            statusRevision++;
            if (stage === 'all') loadingContexts.clear();
            else loadingContexts.delete(stage);
        }
        $('status').textContent = operation === 'load'
            ? `${context === 'preload' ? 'Preloading' : 'Loading'} ${stage.toUpperCase()}${context === 'preload' ? '' : ' for request'}...`
            : `Unloading ${stage.toUpperCase()}...`;
        try {
            await SpeechTools.checked(await fetch('/workspace/lifecycle', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({stage, action: operation})}));
            await refresh();
        } catch (error) {
            if (operation === 'load') loadingContexts.delete(stage);
            await refresh(); throw error;
        }
    }
    function release(stage = 'all') {
        if (!managed) return;
        statusRevision++;
        if (stage === 'all') loadingContexts.clear();
        else loadingContexts.delete(stage);
        refresh().catch(() => {});
    }
    globalThis.SpeechLifecycle = {refresh, action, loading, release, available: () => available};
    async function initialize() {
        const response = await fetch('/proxy/config', {cache: 'no-store'});
        if (!response.ok) throw new Error(`Proxy configuration returned HTTP ${response.status}`);
        managed = true;
        await refresh();
        timer = setInterval(() => refresh().catch(() => {}), 2500);
    }
    initialize().catch(error => {
        $('lifecycle-note').textContent = `Lifecycle unavailable: ${error.message}`;
        for (const stage of ['asr', 'llm', 'tts']) {
            const node = $(`residency-${stage}`);
            node.dataset.state = 'failed';
            node.textContent = `${stage.toUpperCase()} status unavailable`;
        }
    });
    window.addEventListener('pagehide', () => { if (timer) clearInterval(timer); });
})();
