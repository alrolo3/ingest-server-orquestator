import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch


SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from config.config import ServerConfig
from metrics.store import JobMetricsStore
from queues.domain.job import Job
from workers.shared_ingest import SharedFolderScanner
from workers.shared_ingest import canonical_collection_name
from workers.shared_ingest import shared_collection_folder_name
from workers.shared_ingest import update_shared_ingest_state


def _server_config(shared_ingest_dir: Path) -> ServerConfig:
    return ServerConfig(
        app_name="test",
        environment="test",
        inbound_queue_name="queue",
        worker_max_workers=1,
        chunk_max_tokens=8192,
        tokenizer_path=Path("/tmp/tokenizer"),
        docling_artifacts_path=Path("/tmp/docling-artifacts"),
        docling_pp_layout_model_path=Path("/tmp/pp-doclayout-v3"),
        elastic_index_name="open-rag-default",
        elastic_hosts=[],
        shared_ingest_dir=shared_ingest_dir,
        shared_ingest_enabled=True,
        shared_ingest_stable_seconds=0,
    )


class SharedIngestTest(unittest.TestCase):
    def test_collection_name_helpers_strip_and_restore_open_rag_prefix(self) -> None:
        config = _server_config(Path("/tmp/shared"))

        self.assertEqual(
            "open-rag-manuals-qa",
            canonical_collection_name("Manuals QA", config),
        )
        self.assertEqual(
            "manuals-qa",
            shared_collection_folder_name("open-rag-manuals-qa"),
        )
        self.assertEqual("case-rag", shared_collection_folder_name("case-rag"))

    def test_scan_creates_folders_for_default_and_elastic_collections(self) -> None:
        with TemporaryDirectory() as temp_dir:
            shared_root = Path(temp_dir)
            scanner = SharedFolderScanner(
                Event(),
                JobMetricsStore(),
                server_config=_server_config(shared_root),
            )

            with patch.object(
                scanner,
                "_elastic_collection_names",
                return_value={"open-rag-books"},
            ):
                queued = scanner.scan_once()

            self.assertEqual(0, queued)
            self.assertTrue((shared_root / "default" / "output").is_dir())
            self.assertTrue((shared_root / "books" / "output").is_dir())

    def test_scan_queues_stable_file_once_and_records_state(self) -> None:
        store = JobMetricsStore()
        with TemporaryDirectory() as temp_dir:
            shared_root = Path(temp_dir)
            collection_dir = shared_root / "manuals"
            collection_dir.mkdir(parents=True)
            file_path = collection_dir / "guide.pdf"
            file_path.write_bytes(b"%PDF-guide")
            scanner = SharedFolderScanner(
                Event(),
                store,
                server_config=_server_config(shared_root),
            )

            with (
                patch.object(scanner, "_elastic_collection_names", return_value=set()),
                patch("workers.shared_ingest.local_queue.put") as put_item,
            ):
                first = scanner.scan_once()
                second = scanner.scan_once()

            self.assertEqual(1, first)
            self.assertEqual(0, second)
            self.assertEqual(1, put_item.call_count)
            job = put_item.call_args.args[0]
            self.assertEqual("shared-folder", job.input_data["source"])
            self.assertEqual("guide.pdf", job.input_data["file_name"])
            self.assertEqual(str(file_path), job.input_data["file_path"])
            self.assertEqual("open-rag-manuals", job.input_data["collection_name"])
            self.assertEqual("open-rag-manuals", job.settings["elastic_index_name"])

            record = store.get(job.job_id)
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual("open-rag-manuals", record["collection_name"])
            self.assertEqual("shared-folder", record["source"])

            state_path = collection_dir / "output" / ".ingest-state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(job.job_id, state["files"]["guide.pdf"]["job_id"])

    def test_scan_requeues_when_file_identity_changes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            shared_root = Path(temp_dir)
            collection_dir = shared_root / "manuals"
            collection_dir.mkdir(parents=True)
            file_path = collection_dir / "guide.pdf"
            file_path.write_bytes(b"first")
            scanner = SharedFolderScanner(
                Event(),
                JobMetricsStore(),
                server_config=_server_config(shared_root),
            )

            with (
                patch.object(scanner, "_elastic_collection_names", return_value=set()),
                patch("workers.shared_ingest.local_queue.put") as put_item,
            ):
                self.assertEqual(1, scanner.scan_once())
                file_path.write_bytes(b"second-version")
                self.assertEqual(1, scanner.scan_once())

            self.assertEqual(2, put_item.call_count)

    def test_scan_skips_hidden_temp_output_and_nested_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            shared_root = Path(temp_dir)
            collection_dir = shared_root / "manuals"
            output_dir = collection_dir / "output"
            nested_dir = collection_dir / "nested"
            output_dir.mkdir(parents=True)
            nested_dir.mkdir()
            (collection_dir / ".hidden.pdf").write_bytes(b"hidden")
            (collection_dir / "upload.tmp").write_bytes(b"tmp")
            (output_dir / "result.md").write_text("# Result\n", encoding="utf-8")
            (nested_dir / "nested.pdf").write_bytes(b"nested")
            scanner = SharedFolderScanner(
                Event(),
                JobMetricsStore(),
                server_config=_server_config(shared_root),
            )

            with (
                patch.object(scanner, "_elastic_collection_names", return_value=set()),
                patch("workers.shared_ingest.local_queue.put") as put_item,
            ):
                queued = scanner.scan_once()

            self.assertEqual(0, queued)
            self.assertEqual(0, put_item.call_count)

    def test_update_shared_ingest_state_marks_job_completion(self) -> None:
        with TemporaryDirectory() as temp_dir:
            collection_dir = Path(temp_dir) / "manuals"
            output_dir = collection_dir / "output"
            output_dir.mkdir(parents=True)
            file_path = collection_dir / "guide.pdf"
            file_path.write_bytes(b"pdf")
            job_id = "job-1"
            state_path = output_dir / ".ingest-state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "files": {
                            "guide.pdf": {
                                "job_id": job_id,
                                "status": "queued",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            job = Job(
                job_id=job_id,
                parser_type="docling",
                input_data={
                    "source": "shared-folder",
                    "file_path": str(file_path),
                    "file_name": "guide.pdf",
                },
                chunker_type="token",
            )

            self.assertTrue(update_shared_ingest_state(job, "done"))

            state = json.loads(state_path.read_text(encoding="utf-8"))
            entry = state["files"]["guide.pdf"]
            self.assertEqual("done", entry["status"])
            self.assertIn("updated_at", entry)


if __name__ == "__main__":
    unittest.main()
