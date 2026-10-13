"""评测入口的离线边界与错误数据检查。"""

import builtins
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("mathpath_eval_runner", PROJECT_DIR / "evals" / "run.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.dataset = json.loads(runner.DATASET_PATH.read_text(encoding="utf-8"))

    def test_twenty_goals_and_forty_distinct_states(self):
        runner.validate_dataset(self.dataset)
        self.assertEqual(20, len(self.dataset["cases"]))
        self.assertEqual(40, sum(len(case["profiles"]) for case in self.dataset["cases"]))
        self.assertEqual({domain: 5 for domain in runner.DOMAINS},
                         dict(runner.Counter(case["domain"] for case in self.dataset["cases"])))

    def test_default_and_prepare_never_import_model_modules(self):
        real_import = builtins.__import__
        def offline_import(name, *args, **kwargs):
            if name in {"graph_builder", "llm_client", "chatgpt_login", "openai"}:
                self.fail("离线入口不应导入 " + name)
            return real_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=offline_import), redirect_stdout(io.StringIO()):
            self.assertEqual(0, runner.main([]))
            import tempfile
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "bundle.json"
                with patch.object(runner, "output_path", return_value=path):
                    self.assertEqual(0, runner.main(["--prepare", "--case", "homology_quotient"]))
                bundle = json.loads(path.read_text(encoding="utf-8"))
                self.assertIsNone(bundle["cases"][0]["review"]["graph_review"]["scores"]["coverage"])

    def test_live_run_requires_explicit_case_before_importing_model(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as exc:
                runner.main(["--run"])
        self.assertEqual(2, exc.exception.code)

    def test_rejects_duplicate_case_missing_profile_and_bad_source(self):
        bad = deepcopy(self.dataset)
        bad["cases"][1]["id"] = bad["cases"][0]["id"]
        with self.assertRaises(runner.DatasetError):
            runner.validate_dataset(bad)
        bad = deepcopy(self.dataset)
        bad["cases"][0]["profiles"] = bad["cases"][0]["profiles"][:1]
        with self.assertRaises(runner.DatasetError):
            runner.validate_dataset(bad)
        bad = deepcopy(self.dataset)
        bad["cases"][0]["source_sections"][0]["source_id"] = "not_in_sources"
        with self.assertRaises(runner.DatasetError):
            runner.validate_dataset(bad)

    def test_rejects_contradictory_state_and_invalid_teaching_action(self):
        bad = deepcopy(self.dataset)
        profile = bad["cases"][0]["profiles"][0]
        profile["familiar_but_unclear_concepts"] = [profile["known_concepts"][0]]
        with self.assertRaises(runner.DatasetError):
            runner.validate_dataset(bad)
        bad = deepcopy(self.dataset)
        bad["cases"][0]["profiles"][0]["acceptable_first_steps"][0]["action"] = "made_up"
        with self.assertRaises(runner.DatasetError):
            runner.validate_dataset(bad)


if __name__ == "__main__":
    unittest.main()
