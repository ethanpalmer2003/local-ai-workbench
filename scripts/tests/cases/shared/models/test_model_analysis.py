"""Metadata inspection contracts without model inference or network access."""

import json
import struct
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from scripts.config.models.gguf_metadata import inspect_metadata, read_metadata
from scripts.download.models import analyze_model, metadata_evidence, metadata_formats, metadata_summary
from scripts.tests.shared.paths import CasePaths


class ModelAnalysisTests(unittest.TestCase):
    def test_high_ranking_group_has_five_distinct_registered_models(self):
        from scripts.config import models, project_config
        group = json.loads((project_config.CONFIG_DIR / 'asr/leaderboard_group.json').read_text(encoding='utf-8'))
        self.assertEqual(group['name'], 'ASR leaderboard high-ranking')
        self.assertEqual(len({row['model'] for row in group['members']}), 5)
        for row in group['members']:
            self.assertTrue(models.path(row['model_id']).suffix == '.gguf')

    def test_measurements_preserve_context_failed_scope_and_unknown_resources(self):
        with CasePaths(__file__).temporary_directory() as folder:
            path = Path(folder) / 'report.json'
            path.write_text(json.dumps({'execution_context': {'test': True}, 'results': [
                {'model': 'old.gguf', 'status': 'failed', 'timing_scope': 'cold_process_diagnostic'}]}), encoding='utf-8')
            rows: dict[str, Any] = {'new': {'path': 'new.gguf', 'previous_paths': ['old.gguf'], 'ids': []}}
            self.assertEqual(metadata_evidence.measurements(rows, [path]), [])
            metadata_evidence.measurements(rows, [path])
            evidence = rows['new']['measured_metadata']
            self.assertEqual(len(evidence), 1)
            self.assertEqual(evidence[0]['data']['status'], 'failed')
            self.assertNotIn('vram', evidence[0]['data'])

    def test_quality_is_not_transferred_between_nemotron_checkpoints(self):
        rows: dict[str, Any] = {'streaming': {'ids': ['audiocpp/nemotron-3.5-q8_0']}}
        metadata_evidence.published(rows)
        self.assertTrue(rows['streaming']['published_quality'])
        self.assertTrue(all(entry['publisher_model'].endswith('streaming-0.6b')
                            for entry in rows['streaming']['published_quality']))

    def test_voice_reference_transcriber_defaults_to_qwen_asr(self):
        from scripts.config import models, project_config
        from scripts.launchers import launcher_config
        expected = project_config.component('asr/llamacpp').models_dir / 'qwen3_asr/Qwen3-ASR-1.7B-Q8_0.gguf'
        self.assertEqual(models.path('asr/llamacpp/qwen3-asr-1.7b-q8_0'), expected)
        self.assertEqual(launcher_config.QWEN3_ASR.model, expected)

    def test_gguf_arrays_are_bounded_and_scalar_reader_stays_compatible(self):
        def string(value):
            encoded = value.encode()
            return struct.pack('<Q', len(encoded)) + encoded
        data = b'GGUF' + struct.pack('<IQQ', 3, 0, 2)
        data += string('general.architecture') + struct.pack('<I', 8) + string('test')
        data += string('languages') + struct.pack('<IIQ', 9, 8, 3)
        data += b''.join(string(code) for code in ('en', 'fr', 'es'))
        with CasePaths(__file__).temporary_directory() as folder:
            path = Path(folder) / 'test.gguf'
            path.write_bytes(data)
            self.assertEqual(read_metadata(path), {'general.architecture': 'test'})
            result = inspect_metadata(path, array_limit=2)
            self.assertEqual(result['metadata']['languages']['omitted'], 1)
            self.assertEqual(inspect_metadata(path, array_limit=None)['metadata']['languages'], ['en', 'fr', 'es'])
            self.assertEqual(inspect_metadata(path, array_limit=1, full_array_keys=frozenset({'languages'}))['metadata']['languages'], ['en', 'fr', 'es'])

    def test_safetensors_header_and_opaque_pickle_do_not_execute_weights(self):
        with CasePaths(__file__).temporary_directory() as folder:
            path = Path(folder) / 'test.safetensors'
            header = json.dumps({'weight': {'dtype': 'F32', 'shape': [2, 3], 'data_offsets': [0, 24]}}).encode()
            path.write_bytes(struct.pack('<Q', len(header)) + header)
            self.assertEqual(metadata_formats.inspect(path)['tensor_summary']['stored_elements'], 6)
            opaque = Path(folder) / 'unsafe.pth'
            opaque.write_bytes(b'opaque pickle; never execute')
            self.assertEqual(metadata_formats.inspect(opaque)['metadata'], {})

    def test_language_disagreement_is_preserved_and_unknown_is_not_false(self):
        record = {'ids': [], 'groups': [], 'path': 'test.gguf',
                  'local': {'metadata': {'languages': ['en', 'auto']}},
                  'hub': [{'repo': 'publisher/test', 'card': {'language': ['fr']}}]}
        result = metadata_summary.summary(record, {'models': []})
        self.assertEqual([claim['codes'] for claim in result['language_claims']], [['en'], ['fr']])
        self.assertTrue(result['review_flags'])
        self.assertIsNone(result['capabilities'])

    def test_hub_configs_keep_subdirectory_identity(self):
        records = {name: {'registry': [{'url': f'https://huggingface.co/org/repo/resolve/main/{name}/model.gguf'}]}
                   for name in ('first', 'second')}
        with patch.object(analyze_model.metadata_sources, 'hub_metadata', side_effect=lambda source: {'file': source.filename}):
            analyze_model.enrich_hub(records, {})
        self.assertNotEqual(records['first']['hub'][0]['file'], records['second']['hub'][0]['file'])

    def test_malformed_header_is_recorded_without_aborting_inventory(self):
        with CasePaths(__file__).temporary_directory() as folder:
            path = Path(folder) / 'broken.gguf'
            path.write_bytes(b'GGUF')
            result = analyze_model.inspect_record({'path': str(path), 'groups': [], 'ids': []}, {})
            self.assertEqual(result['status'], 'error')


if __name__ == '__main__':
    unittest.main()
