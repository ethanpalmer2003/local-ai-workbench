// Owned NDJSON bridge to Node's built-in WebSocket; no model or pacing policy here.
import readline from 'node:readline';
const sockets = new Map();
const emit = value => process.stdout.write(JSON.stringify(value) + '\n');
const fail = (id, error) => emit({id, type: 'error', error: String(error)});
emit({type: 'ready'});
for await (const line of readline.createInterface({input: process.stdin})) {
    let c;
    try {
        if (line.length > 131072) throw new Error('WebSocket command too large');
        c = JSON.parse(line);
        if (c.op === 'open') {
            if (sockets.size >= 2 || sockets.has(c.id)) throw new Error('WebSocket capacity exceeded');
            const url = new URL(c.url);
            if (url.protocol !== 'ws:' || !['127.0.0.1', 'localhost'].includes(url.hostname)) throw new Error('Expected local WebSocket');
            const ws = new WebSocket(url);
            sockets.set(c.id, ws);
            ws.addEventListener('open', () => ws.send(JSON.stringify({type: 'session.update', session: c.session})));
            ws.addEventListener('message', event => {
                try {
                    if (typeof event.data !== 'string' || event.data.length > 1048576) throw new Error('Invalid WebSocket event');
                    emit({id: c.id, event: JSON.parse(event.data)});
                } catch (error) { fail(c.id, error); ws.close(); }
            });
            ws.addEventListener('error', event => fail(c.id, event.message || 'WebSocket error'));
            ws.addEventListener('close', () => { sockets.delete(c.id); emit({id: c.id, type: 'closed'}); });
        } else {
            const ws = sockets.get(c.id);
            if (c.op === 'close') { ws?.close(); continue; }
            if (!ws || ws.readyState !== WebSocket.OPEN) throw new Error('WebSocket is not open');
            if (ws.bufferedAmount > 1048576) throw new Error('WebSocket upload fell behind');
            if (c.op === 'audio') ws.send(Buffer.from(c.audio, 'base64'));
            else if (c.op === 'commit') ws.send(JSON.stringify({type: 'input_audio_buffer.commit'}));
            else throw new Error('Unknown WebSocket command');
        }
    } catch (error) { fail(c?.id, error); }
}
for (const ws of sockets.values()) ws.close();
