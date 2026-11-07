"""Validated speech-setup switching; the launcher owns process changes after gateway shutdown."""

import threading
from contextlib import contextmanager
from typing import Any

from scripts.launchers.asr.shared import practice_asr, practice_models
from scripts.launchers.llamacpp import chat_models


class Selection:
    def __init__(self, engine, tts=None, llm=None):
        self.engine, self.tts = engine, tts or practice_models.tts_id()
        self.llm = llm or chat_models.default_id()
        self.pending = None
        self.lock = threading.RLock()
        self.active = 0
        self.error: str | None = None

    def catalog(self) -> dict[str, Any]:
        return {'asr': practice_asr.asr_models(), 'tts': practice_models.tts_models(),
                'llm': chat_models.catalog(),
                'selected': {'asr': self.engine.value, 'tts': self.tts, 'llm': self.llm}, 'error': self.error}

    @contextmanager
    def request(self):
        with self.lock:
            self.active += 1
        try:
            yield
        finally:
            with self.lock:
                self.active -= 1

    def select(self, value):
        if not isinstance(value, dict):
            raise ValueError('Speech setup must be an object')
        with self.lock:
            if self.active > 1 or self.pending:
                raise RuntimeError('Another request is active; retry after it completes')
            catalog = self.catalog()
            for kind in ('asr', 'tts'):
                row = next((row for row in catalog[kind] if row['id'] == value.get(kind)), None)
                if row is None or not row['available']:
                    raise ValueError(f'Unavailable {kind} selection')
            if 'llm' in value:
                row = next((row for row in catalog.get('llm', []) if row['id'] == value['llm']), None)
                if row is None or not row['available']:
                    raise ValueError('Unavailable llm selection')
            self.pending = {'asr': value['asr'], 'tts': value['tts']}
            if 'llm' in value:
                self.pending['llm'] = value['llm']
            return self.pending
