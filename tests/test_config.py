import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from config import config as config_module
from config.gpu import configure_gpu_environment
from dispatcher.elastic.elastic import OPEN_RAG_PIPELINE, build_open_rag_mappings


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
        self.assertEqual(1, settings.worker_max_workers)
        self.assertEqual(8192, settings.chunk_max_tokens)
        self.assertEqual(Path("/tokenizer"), settings.tokenizer_path)
        self.assertEqual(
            Path("/docling-models/artifacts"),
            settings.docling_artifacts_path,
        )
        self.assertEqual(
            Path("/docling-models/pp-doclayout-v3"),
            settings.docling_pp_layout_model_path,
        )
        self.assertEqual(
            Path("/docling-models/models/MinerU2.5-Pro-2605-1.2B"),
            settings.docling_mineru_model_path,
        )
        self.assertEqual("PCI_BUS_ID", settings.cuda_device_order)
        self.assertEqual("0", settings.visible_cuda_devices)
        self.assertEqual(0, settings.logical_cuda_device_index)
        self.assertEqual("cuda:0", settings.docling_device)
        self.assertTrue(settings.docling_ocr_enabled)
        self.assertEqual("easyocr", settings.docling_ocr_engine)
        self.assertEqual(["es", "en"], settings.docling_ocr_langs)
        self.assertEqual("auto", settings.docling_mineru_device)
        self.assertEqual("auto", settings.docling_mineru_dtype)
        self.assertEqual(1, settings.docling_mineru_batch_size)
        self.assertFalse(settings.docling_mineru_image_analysis)
        self.assertEqual(2.0, settings.docling_surya_scale)
        self.assertEqual(1.0, settings.docling_surya_confidence)
        self.assertIsNone(settings.docling_surya_inference_url)
        self.assertIsNone(settings.docling_surya_inference_backend)
        self.assertEqual(8, settings.docling_surya_inference_parallel)
        self.assertTrue(settings.docling_surya_keep_alive)
        self.assertFalse(settings.docling_force_full_page_ocr)
        self.assertEqual(0.05, settings.docling_ocr_bitmap_area_threshold)
        self.assertEqual(8, settings.docling_ocr_batch_size)
        self.assertEqual(4, settings.docling_layout_batch_size)
        self.assertEqual(8, settings.docling_table_batch_size)
        self.assertEqual(16, settings.docling_queue_max_size)
        self.assertEqual(8, settings.docling_accelerator_threads)
        self.assertTrue(settings.docling_picture_description_enabled)
        self.assertTrue(settings.docling_picture_classification_enabled)
        self.assertEqual(16, settings.docling_picture_description_concurrency)
        self.assertEqual(240, settings.docling_picture_description_timeout)
        self.assertEqual(2.0, settings.docling_images_scale)
        self.assertEqual("accurate", settings.docling_table_mode)
        self.assertFalse(settings.docling_code_enrichment_enabled)
        self.assertFalse(settings.docling_formula_enrichment_enabled)
        self.assertEqual(["https://localhost:9200"], settings.elastic_hosts)
        self.assertEqual(
            "RW9RbG1aNEJ4QVZwbFVaNjNhOEc6QTY1b1V2cDU4MUUxWHZjeTkxTkx4UQ==",
            settings.elastic_api_key,
        )
        self.assertEqual("open-rag-embeddings-v4", settings.elastic_index_name)
        self.assertEqual(
            "open_rag_embeddings_v4_multilingual_semantic_pipeline",
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
        self.assertEqual(
            "http://vllm-qwen35-9b:8007/v1/chat/completions",
            settings.docling_picture_description_url,
        )
        self.assertEqual("Qwen3.5-9B", settings.docling_picture_description_model)

    def test_server_config_constants_ignore_environment(self) -> None:
        env = {
            "APP_NAME": "custom-app",
            "INBOUND_QUEUE_NAME": "documents",
            "CHUNK_MAX_TOKENS": "4096",
            "CUDA_DEVICE_ORDER": "FASTEST_FIRST",
            "CUDA_VISIBLE_DEVICES": "2,3",
            "LOGICAL_CUDA_DEVICE_INDEX": "1",
            "DOCLING_DEVICE": "cuda:1",
            "TOKENIZER_PATH": "/tmp/tokenizer",
            "DOCLING_ARTIFACTS_PATH": "/tmp/docling-artifacts",
            "DOCLING_MINERU_DEVICE": "cpu",
            "DOCLING_OCR_ENGINE": "rapidocr",
            "DOCLING_OCR_LANGS": "english",
            "INGEST_WORKER_MAX_WORKERS": "2",
        }
        with patch.dict(os.environ, env, clear=True):
            config_module._SERVER_CONFIG = None

            settings = config_module.load_server_config()

        self.assertEqual("ingest-server-orquestator", settings.app_name)
        self.assertEqual("inbound", settings.inbound_queue_name)
        self.assertEqual(2, settings.worker_max_workers)
        self.assertEqual(8192, settings.chunk_max_tokens)
        self.assertEqual(Path("/tokenizer"), settings.tokenizer_path)
        self.assertEqual(
            Path("/docling-models/artifacts"),
            settings.docling_artifacts_path,
        )
        self.assertEqual(
            Path("/docling-models/pp-doclayout-v3"),
            settings.docling_pp_layout_model_path,
        )
        self.assertEqual(
            Path("/docling-models/models/MinerU2.5-Pro-2605-1.2B"),
            settings.docling_mineru_model_path,
        )
        self.assertEqual("PCI_BUS_ID", settings.cuda_device_order)
        self.assertEqual("0", settings.visible_cuda_devices)
        self.assertEqual(0, settings.logical_cuda_device_index)
        self.assertEqual("cuda:0", settings.docling_device)
        self.assertEqual("rapidocr", settings.docling_ocr_engine)
        self.assertEqual(["english"], settings.docling_ocr_langs)
        self.assertEqual("cpu", settings.docling_mineru_device)

    def test_configure_gpu_environment_sets_offline_model_environment(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config_module._SERVER_CONFIG = None
            settings = config_module.load_server_config()

            configure_gpu_environment(settings)

            self.assertEqual("PCI_BUS_ID", os.environ["CUDA_DEVICE_ORDER"])
            self.assertEqual("0", os.environ["CUDA_VISIBLE_DEVICES"])
            self.assertEqual("cuda:0", os.environ["DOCLING_DEVICE"])
            self.assertEqual(
                "/docling-models/artifacts",
                os.environ["DOCLING_ARTIFACTS_PATH"],
            )
            self.assertEqual(
                "expandable_segments:True",
                os.environ["PYTORCH_CUDA_ALLOC_CONF"],
            )
            self.assertEqual("1", os.environ["HF_HUB_OFFLINE"])
            self.assertEqual("1", os.environ["TRANSFORMERS_OFFLINE"])

    def test_load_server_config_uses_environment_overrides(self) -> None:
        env = {
            "APP_ENV": "prod",
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
            "DOCLING_PICTURE_DESCRIPTION_URL": "http://vlm:8007/v1/chat/completions",
            "DOCLING_PICTURE_DESCRIPTION_MODEL": "CustomVLM",
            "DOCLING_OCR_ENABLED": "false",
            "DOCLING_OCR_ENGINE": "auto",
            "DOCLING_OCR_LANGS": "en,es",
            "DOCLING_MINERU_DEVICE": "cpu",
            "DOCLING_MINERU_DTYPE": "bfloat16",
            "DOCLING_MINERU_BATCH_SIZE": "2",
            "DOCLING_MINERU_IMAGE_ANALYSIS": "true",
            "DOCLING_SURYA_SCALE": "3.0",
            "DOCLING_SURYA_CONFIDENCE": "0.75",
            "DOCLING_SURYA_INFERENCE_URL": "http://surya:8000/v1",
            "DOCLING_SURYA_INFERENCE_BACKEND": "vllm",
            "DOCLING_SURYA_INFERENCE_PARALLEL": "0",
            "DOCLING_SURYA_KEEP_ALIVE": "false",
            "DOCLING_FORCE_FULL_PAGE_OCR": "true",
            "DOCLING_OCR_BITMAP_AREA_THRESHOLD": "0.1",
            "INGEST_WORKER_MAX_WORKERS": "0",
            "DOCLING_OCR_BATCH_SIZE": "3",
            "DOCLING_LAYOUT_BATCH_SIZE": "2",
            "DOCLING_TABLE_BATCH_SIZE": "5",
            "DOCLING_QUEUE_MAX_SIZE": "7",
            "DOCLING_ACCELERATOR_THREADS": "0",
            "DOCLING_PICTURE_DESCRIPTION_ENABLED": "false",
            "DOCLING_PICTURE_CLASSIFICATION_ENABLED": "false",
            "DOCLING_PICTURE_DESCRIPTION_CONCURRENCY": "0",
            "DOCLING_PICTURE_DESCRIPTION_TIMEOUT": "0",
            "DOCLING_IMAGES_SCALE": "0",
            "DOCLING_TABLE_MODE": "fast",
            "DOCLING_CODE_ENRICHMENT_ENABLED": "true",
            "DOCLING_FORMULA_ENRICHMENT_ENABLED": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            config_module._SERVER_CONFIG = None

            settings = config_module.load_server_config()

        self.assertEqual("ingest-server-orquestator", settings.app_name)
        self.assertEqual("prod", settings.environment)
        self.assertEqual("inbound", settings.inbound_queue_name)
        self.assertEqual(1, settings.worker_max_workers)
        self.assertEqual(8192, settings.chunk_max_tokens)
        self.assertEqual(Path("/tokenizer"), settings.tokenizer_path)
        self.assertEqual(
            Path("/docling-models/artifacts"),
            settings.docling_artifacts_path,
        )
        self.assertEqual(
            Path("/docling-models/pp-doclayout-v3"),
            settings.docling_pp_layout_model_path,
        )
        self.assertEqual("PCI_BUS_ID", settings.cuda_device_order)
        self.assertEqual("0", settings.visible_cuda_devices)
        self.assertEqual(0, settings.logical_cuda_device_index)
        self.assertEqual("cuda:0", settings.docling_device)
        self.assertFalse(settings.docling_ocr_enabled)
        self.assertEqual("auto", settings.docling_ocr_engine)
        self.assertEqual(["en", "es"], settings.docling_ocr_langs)
        self.assertEqual("cpu", settings.docling_mineru_device)
        self.assertEqual("bfloat16", settings.docling_mineru_dtype)
        self.assertEqual(2, settings.docling_mineru_batch_size)
        self.assertTrue(settings.docling_mineru_image_analysis)
        self.assertEqual(3.0, settings.docling_surya_scale)
        self.assertEqual(0.75, settings.docling_surya_confidence)
        self.assertEqual(
            "http://surya:8000/v1",
            settings.docling_surya_inference_url,
        )
        self.assertEqual("vllm", settings.docling_surya_inference_backend)
        self.assertEqual(1, settings.docling_surya_inference_parallel)
        self.assertFalse(settings.docling_surya_keep_alive)
        self.assertTrue(settings.docling_force_full_page_ocr)
        self.assertEqual(0.1, settings.docling_ocr_bitmap_area_threshold)
        self.assertEqual(3, settings.docling_ocr_batch_size)
        self.assertEqual(2, settings.docling_layout_batch_size)
        self.assertEqual(5, settings.docling_table_batch_size)
        self.assertEqual(7, settings.docling_queue_max_size)
        self.assertEqual(1, settings.docling_accelerator_threads)
        self.assertFalse(settings.docling_picture_description_enabled)
        self.assertFalse(settings.docling_picture_classification_enabled)
        self.assertEqual(1, settings.docling_picture_description_concurrency)
        self.assertEqual(1, settings.docling_picture_description_timeout)
        self.assertEqual(0.1, settings.docling_images_scale)
        self.assertEqual("fast", settings.docling_table_mode)
        self.assertTrue(settings.docling_code_enrichment_enabled)
        self.assertTrue(settings.docling_formula_enrichment_enabled)
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
        self.assertFalse(settings.elastic_http_compress)
        self.assertEqual("10m", settings.elastic_bulk_api_timeout)
        self.assertEqual(600, settings.elastic_bulk_request_timeout_seconds)
        self.assertEqual(25, settings.elastic_bulk_batch_size)
        self.assertEqual(2, settings.elastic_bulk_max_retries)
        self.assertEqual(
            "http://vlm:8007/v1/chat/completions",
            settings.docling_picture_description_url,
        )
        self.assertEqual("CustomVLM", settings.docling_picture_description_model)

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
        self.assertEqual(
            {
                "inference_id": "bge-m3-sparse",
                "task_type": "sparse_embedding",
            },
            mappings["_meta"]["sparse_semantic_inference"],
        )
        for field_name in ("content_sparse", "clean_title", "headings"):
            field_mapping = mappings["properties"][field_name]
            self.assertEqual("semantic_text", field_mapping["type"])
            self.assertEqual(
                "bge-m3-sparse",
                field_mapping["inference_id"],
            )
            self.assertEqual({"strategy": "none"}, field_mapping["chunking_settings"])
            self.assertNotIn("index_options", field_mapping)
            self.assertNotIn("model_settings", field_mapping)
        self.assertNotIn("title_semantic", mappings["properties"])
        self.assertNotIn("title_sparse", mappings["properties"])
        self.assertNotIn("raw_text", mappings["properties"])

    def test_elastic_pipeline_removes_old_title_and_raw_fields(self) -> None:
        remove_fields = [
            field
            for processor in OPEN_RAG_PIPELINE["processors"]
            if "remove" in processor
            for field in processor["remove"]["field"]
        ]

        self.assertIn("title_semantic", remove_fields)
        self.assertIn("title_sparse", remove_fields)
        self.assertIn("raw_text", remove_fields)
        self.assertIn("raw_data", remove_fields)

    def test_docling_table_mode_validates_supported_values(self) -> None:
        with patch.dict(os.environ, {"DOCLING_TABLE_MODE": "precise"}, clear=True):
            config_module._SERVER_CONFIG = None

            with self.assertRaisesRegex(ValueError, "DOCLING_TABLE_MODE"):
                config_module.load_server_config()


if __name__ == "__main__":
    unittest.main()
