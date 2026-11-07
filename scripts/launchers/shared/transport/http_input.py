"""Bounded exact reads for local chunked PCM uploads; no model-specific framing."""


def chunks(handler, *, limit=16000 * 2 * 32):
    if handler.headers.get("Transfer-Encoding", "").lower() != "chunked":
        raise ValueError("Expected chunked PCM upload")
    total = 0
    while True:
        line = handler.rfile.readline(128)
        if not line.endswith(b"\r\n"):
            raise ValueError("Invalid chunk header")
        size = int(line.strip(), 16)
        if size < 0 or total + size > limit:
            raise ValueError("PCM upload limit exceeded")
        if size == 0:
            if handler.rfile.read(2) != b"\r\n":
                raise ValueError("Unexpected PCM trailers")
            return
        data = handler.rfile.read(size)
        if len(data) != size or handler.rfile.read(2) != b"\r\n":
            raise ValueError("Incomplete PCM upload")
        if len(data) % 2:
            raise ValueError("PCM16 needs complete samples")
        total += size
        yield data
