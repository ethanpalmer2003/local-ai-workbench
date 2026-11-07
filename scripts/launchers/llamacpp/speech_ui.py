"""Serve the installed native UI through the existing same-origin speech gateway."""

import mimetypes
from urllib.parse import parse_qs, unquote, urlsplit

from scripts.config import project_config as project_cfg
from scripts.launchers.proxy_util import send_bytes


def route(handler, method, runtime) -> bool:
    if method != 'GET' or runtime is None:
        return False
    # A native UI PWA must not install a worker over the shared workspace origin.
    if handler.headers.get('Service-Worker') == 'script':
        send_bytes(handler, 404, b'Service workers are disabled on the shared speech origin', 'text/plain')
        return True
    url = urlsplit(handler.path)
    if url.path == '/llama-ui':
        handler.send_response(302)
        handler.send_header('Location', '/?ui=llama')
        handler.send_header('Content-Length', '0')
        handler.end_headers()
        return True
    if url.path == '/llama-speech.js':
        path = project_cfg.component('llamacpp').launcher_dir / 'speech_ui.js'
        send_bytes(handler, 200, path.read_bytes(), 'text/javascript')
        return True
    directory = project_cfg.LLAMACPP_SPEECH_UI_DIR.resolve()
    asset = (directory / unquote(url.path).lstrip('/')).resolve()
    if asset.is_relative_to(directory) and asset.is_file() and asset.name != 'index.html':
        send_bytes(handler, 200, asset.read_bytes(), mimetypes.guess_type(asset.name)[0] or 'application/octet-stream')
        return True
    if url.path != '/' or parse_qs(url.query).get('ui') != ['llama']:
        return False
    index = directory / 'index.html'
    if not index.is_file():
        raise RuntimeError('Build the native speech UI first; see scripts/launchers/llamacpp/SPEECH-UI.md')
    # Native UI requires its chat server. ASR/TTS remain lazy and share the workspace lifecycle.
    runtime.load('llm')
    page = index.read_text(encoding='utf-8')
    scripts = ''.join(f'<script src="{path}"></script>' for path in (
        '/launchers/shared/browser/pcm_audio.js', '/launchers/shared/browser/speech_tools.js',
        '/launchers/shared/browser/speech_client.js', '/llama-speech.js'))
    if '</head>' not in page:
        raise RuntimeError('Native llama-ui HTML has no head; speech integration not injected')
    send_bytes(handler, 200, page.replace('</head>', scripts + '</head>', 1).encode(), 'text/html; charset=utf-8')
    return True
