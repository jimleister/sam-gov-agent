"""Offline smoke test for the full report path of every scheduled scanner."""
import contextlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCANNERS = ["script.py", "script_pest.py", "script_usace_asia.py", "script_inspection_oilgas.py", "script_catholic_southeast.py"]

class ScannerSmokeTests(unittest.TestCase):
    def test_each_scanner_completes_and_writes_query_metrics(self):
        source = Path(__file__).resolve().parent
        for scanner in SCANNERS:
            with self.subTest(scanner=scanner):
                spec = importlib.util.spec_from_file_location(scanner[:-3], source / scanner)
                module = importlib.util.module_from_spec(spec)
                import sys
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
                with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"SAM_API_KEY": "test-only", "SEND_EMAIL": "0"}), patch.object(module, "sam_search", return_value={"opportunitiesData": []}):
                    previous = Path.cwd()
                    try:
                        os.chdir(directory)
                        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                            self.assertEqual(module.run(), 0)
                        metrics = json.loads(Path("runtime_metrics.json").read_text())
                        self.assertEqual(metrics["scanner"], scanner)
                        self.assertTrue(metrics["queries"])
                        self.assertEqual(metrics["api_calls"], len(metrics["queries"]))
                        self.assertTrue(Path("email_draft.txt").exists())
                    finally:
                        os.chdir(previous)

if __name__ == "__main__":
    unittest.main()
