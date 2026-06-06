import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from config import config as config_module
from dispatcher.elastic.elastic import build_open_rag_mappings


class ServerConfigTest(unittest.TestCase):
    def tearDown(self) -> None:
        config_module._SERVER_CONFIG = None

    def test_load_server_config_uses_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config_module._SERVER_CONFIG = None

            settings = config_module.load_server_config()

        self.assertEqual("ingest-server-orquestator", settings.app_name)
        self.assertEqual("local", settings.environment)
        self.assertEqual("inbound", settings.inbound_queue_name)
        self.assertEqual(2048, settings.chunk_max_tokens)
        self.assertEqual(
            Path("/datastore/models/tokenizers/qwen3-embedding-4b/"),
            settings.tokenizer_path,
        )
        self.assertEqual("PCI_BUS_ID", settings.cuda_device_order)
        self.assertEqual("4", settings.physical_cuda_device)
        self.assertEqual("4", settings.visible_cuda_devices)
        self.assertEqual(0, settings.logical_cuda_device_index)
        self.assertEqual("cuda:0", settings.docling_device)
        self.assertEqual(["https://localhost:9200"], settings.elastic_hosts)
        self.assertEqual(
            "RW9RbG1aNEJ4QVZwbFVaNjNhOEc6QTY1b1V2cDU4MUUxWHZjeTkxTkx4UQ==",
            settings.elastic_api_key,
        )
        self.assertEqual("open-rag-embeddings-v3", settings.elastic_index_name)
        self.assertEqual(
            "open_rag_embeddings_v3_multilingual_semantic_pipeline",
            settings.elastic_pipeline_name,
        )
        self.assertEqual("qwen3-embedding-4b", settings.elastic_inference_id)
        self.assertFalse(settings.elastic_verify_certs)
        self.assertFalse(settings.elastic_ssl_show_warn)
        self.assertTrue(settings.elastic_http_compress)
        self.assertEqual("30m", settings.elastic_bulk_api_timeout)
        self.assertEqual(1800, settings.elastic_bulk_request_timeout_seconds)
        self.assertEqual(100, settings.elastic_bulk_batch_size)
        self.assertEqual(5, settings.elastic_bulk_max_retries)

    def test_load_server_config_uses_environment_overrides(self) -> None:
        env = {
            "APP_NAME": "custom-app",
            "APP_ENV": "prod",
            "INBOUND_QUEUE_NAME": "documents",
            "CHUNK_MAX_TOKENS": "4096",
            "TOKENIZER_PATH": "/tmp/tokenizer",
            "CUDA_DEVICE_ORDER": "FASTEST_FIRST",
            "PHYSICAL_CUDA_DEVICE": "2",
            "CUDA_VISIBLE_DEVICES": "2,3",
            "LOGICAL_CUDA_DEVICE_INDEX": "1",
            "DOCLING_DEVICE": "cuda:1",
            "ELASTIC_HOSTS": "https://one:9200,https://two:9200",
            "ELASTIC_API_KEY": "",
            "ELASTIC_INDEX_NAME": "custom-index",
            "ELASTIC_PIPELINE_NAME": "custom-pipeline",
            "ELASTIC_INFERENCE_ID": "custom-inference",
            "ELASTIC_VERIFY_CERTS": "true",
            "ELASTIC_SSL_SHOW_WARN": "1",
            "ELASTIC_HTTP_COMPRESS": "false",
            "ELASTIC_BULK_API_TIMEOUT": "10m",
            "ELASTIC_BULK_REQUEST_TIMEOUT_SECONDS": "600",
            "ELASTIC_BULK_BATCH_SIZE": "25",
            "ELASTIC_BULK_MAX_RETRIES": "2",
        }
        with patch.dict(os.environ, env, clear=True):
            config_module._SERVER_CONFIG = None

            settings = config_module.load_server_config()

        self.assertEqual("custom-app", settings.app_name)
        self.assertEqual("prod", settings.environment)
        self.assertEqual("documents", settings.inbound_queue_name)
        self.assertEqual(4096, settings.chunk_max_tokens)
        self.assertEqual(Path("/tmp/tokenizer"), settings.tokenizer_path)
        self.assertEqual("FASTEST_FIRST", settings.cuda_device_order)
        self.assertEqual("2", settings.physical_cuda_device)
        self.assertEqual("2,3", settings.visible_cuda_devices)
        self.assertEqual(1, settings.logical_cuda_device_index)
        self.assertEqual("cuda:1", settings.docling_device)
        self.assertEqual(
            ["https://one:9200", "https://two:9200"],
            settings.elastic_hosts,
        )
        self.assertIsNone(settings.elastic_api_key)
        self.assertEqual("custom-index", settings.elastic_index_name)
        self.assertEqual("custom-pipeline", settings.elastic_pipeline_name)
        self.assertEqual("custom-inference", settings.elastic_inference_id)
        self.assertTrue(settings.elastic_verify_certs)
        self.assertTrue(settings.elastic_ssl_show_warn)
        self.assertTrue(settings.elastic_http_compress)
        self.assertEqual("30m", settings.elastic_bulk_api_timeout)
        self.assertEqual(1800, settings.elastic_bulk_request_timeout_seconds)
        self.assertEqual(100, settings.elastic_bulk_batch_size)
        self.assertEqual(5, settings.elastic_bulk_max_retries)

    def test_elastic_url_is_single_host_fallback(self) -> None:
        with patch.dict(
            os.environ,
            {"ELASTIC_URL": "https://elastic:9200"},
            clear=True,
        ):
            config_module._SERVER_CONFIG = None

            settings = config_module.load_server_config()

        self.assertEqual(["https://elastic:9200"], settings.elastic_hosts)

    def test_elastic_mapping_uses_configured_inference_id(self) -> None:
        mappings = build_open_rag_mappings("custom-inference")

        self.assertEqual(
            "custom-inference",
            mappings["_meta"]["inference_id"],
        )
        self.assertEqual(
            "custom-inference",
            mappings["properties"]["content"]["inference_id"],
        )


if __name__ == "__main__":
    unittest.main()
