import pickle
import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ingest-server-orquestator"
sys.path.insert(0, str(SRC_DIR))

from workers.job_runner import _serializable_job_error


class UnpickleableError(Exception):
    def __reduce__(self):  # pragma: no cover - called by pickle internals
        raise TypeError("cannot pickle")


class JobRunnerTest(unittest.TestCase):
    def test_serializable_job_error_wraps_unpickleable_exception(self) -> None:
        error = _serializable_job_error(UnpickleableError("pipeline failed"))

        pickle.dumps(error)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual("UnpickleableError: pipeline failed", str(error))


if __name__ == "__main__":
    unittest.main()
