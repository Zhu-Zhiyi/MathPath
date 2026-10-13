"""Meaningful offline A/B integrity, human scoring and credential-boundary checks."""
import builtins
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
import csv
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("mathpath_compare_tests", PROJECT / "evals" / "compare.py")
compare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compare)
from evals import review


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.dataset, self.dataset_hash = compare.load_dataset()
        self.selected = self.dataset["cases"][:1]
        self.graph = {"target_id": "target", "nodes": [
            {"id": "base", "label": "先修概念", "prerequisite_sets": []},
            {"id": "target", "label": "目标概念", "prerequisite_sets": [["base"]]},
        ]}
        self.mapping = compare.mapping_template(self.dataset, self.selected, self.dataset_hash)
        item = self.mapping["cases"][0]
        item["reviewed_graph"] = self.graph
        item["graph_approval"] = {"approved": True, "reviewer": "Reviewer01", "evidence": ["Synthetic fixture; not a real mathematical evaluation."]}
        for profile in item["profiles"]:
            profile["known_node_ids"] = ["base"]
            profile["mapping_approval"] = deepcopy(item["graph_approval"])
        self.configuration = SimpleNamespace(model="selected-model-fixture", provider="api", api_format="responses", output_mode="json_schema", api_key="NEVER_SERIALIZE", base_url="https://private-endpoint.example/v1")

    def decision(self, *, condition="A"):
        return {"focus_node_id": "target" if condition == "B" else None, "focus_concept": "概念",
                "action": "concrete_example", "depth": 2, "rationale": "合成测试理由",
                "explanation": "合成测试解释", "check_question": "合成测试问题？"}

    def generate(self, prompt, **kwargs):
        self.assertIs(kwargs["configuration"], self.configuration)
        self.assertEqual(compare.INSTRUCTIONS, kwargs["instructions"])
        self.assertEqual(compare.DECISION_SCHEMA, kwargs["json_schema"])
        value = json.loads(prompt)
        return json.dumps(self.decision(condition="B" if "reviewed_graph" in value else "A"), ensure_ascii=False)

    def collection(self, folder, generator=None, *, trials=1):
        path = Path(folder) / "collection.jsonl"
        compare.collect(path, self.dataset, self.selected, self.mapping, self.dataset_hash, trials, 17, generator or self.generate, self.configuration)
        return path

    def save(self, path, value):
        Path(path).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def test_offline_default_and_prepare_never_import_or_access_credentials(self):
        original_import = builtins.__import__
        blocked = {"graph_builder", "llm_client", "model_settings", "chatgpt_login", "openai"}
        def guarded(name, *args, **kwargs):
            if name in blocked:
                self.fail("Offline imported credential/model dependency: " + name)
            return original_import(name, *args, **kwargs)
        with tempfile.TemporaryDirectory() as folder, patch("builtins.__import__", side_effect=guarded), redirect_stdout(io.StringIO()):
            self.assertEqual(0, compare.main([]))
            self.assertEqual(0, compare.main(["--prepare", "--out", folder]))
            mapping = json.loads((Path(folder) / "reviewed-mapping-template.json").read_text(encoding="utf-8"))
            self.assertEqual(20, len(mapping["cases"]))
            self.assertEqual(40, sum(len(case["profiles"]) for case in mapping["cases"]))
            with (Path(folder) / "human-scoring-plan.csv").open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(80, len(rows))
            self.assertTrue(all(row[dimension] == "" for row in rows for dimension in compare.DIMENSIONS))

    def test_explicit_live_guard_precedes_model_import(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            for arguments in (["--run"], ["--run", "--case", "all"], ["--run", "--mapping", "missing.json"]):
                with self.assertRaises(SystemExit) as caught:
                    compare.main(arguments)
                self.assertEqual(2, caught.exception.code)

    def test_approval_required_and_mapping_never_guessed_from_labels(self):
        bad = deepcopy(self.mapping)
        bad["cases"][0]["graph_approval"]["approved"] = False
        with self.assertRaises(compare.EvaluationError):
            compare.validate_mapping(bad, self.dataset, self.dataset_hash, selected=self.selected, require_approved=True)
        bad = deepcopy(self.mapping)
        bad["cases"][0]["profiles"][0]["known_node_ids"] = ["先修概念"]
        with self.assertRaises(compare.EvaluationError):
            compare.validate_mapping(bad, self.dataset, self.dataset_hash)
        bad = deepcopy(self.mapping)
        bad["cases"][0]["profiles"][0]["mapping_approval"]["evidence"] = []
        with self.assertRaises(compare.EvaluationError):
            compare.validate_mapping(bad, self.dataset, self.dataset_hash)

    def test_both_conditions_get_same_complete_profile_and_same_instructions(self):
        calls = []
        def recording(prompt, **kwargs):
            calls.append((json.loads(prompt), kwargs))
            return self.generate(prompt, **kwargs)
        with tempfile.TemporaryDirectory() as folder:
            path = self.collection(folder, recording, trials=2)
            header, records, completeness = compare.load_collection(path, self.dataset, self.dataset_hash)
        self.assertEqual(8, len(records))
        self.assertEqual({"expected": 8, "recorded": 8, "missing": 0}, completeness)
        self.assertEqual("selected-model-fixture", header["model_metadata"]["model"])
        self.assertNotIn("api_key", header["model_metadata"])
        self.assertNotIn("base_url", header["model_metadata"])
        grouped = {}
        for record in records:
            grouped.setdefault((record["case_id"], record["profile_id"], record["trial"]), {})[record["condition"]] = record
        for conditions in grouped.values():
            plain, graph = conditions["A"]["input"], conditions["B"]["input"]
            self.assertEqual(set(plain), {"goal", "query", "self_report", "known_concepts", "familiar_but_unclear_concepts"})
            self.assertEqual(plain, {key: graph[key] for key in plain})
            self.assertEqual(self.graph, graph["reviewed_graph"])
            self.assertEqual(["base"], graph["manually_mapped_known_ids"])

    def test_failures_are_streamed_with_type_only_and_no_raw_error(self):
        index = 0
        def failure(prompt, **kwargs):
            nonlocal index
            index += 1
            if index == 2:
                raise RuntimeError("NEVER_LEAK_API_KEY_OR_RESPONSE_BODY")
            return self.generate(prompt, **kwargs)
        with tempfile.TemporaryDirectory() as folder:
            path = self.collection(folder, failure)
            text = path.read_text(encoding="utf-8")
            _, records, _ = compare.load_collection(path, self.dataset, self.dataset_hash)
            self.assertNotIn("NEVER_LEAK", text)
            self.assertNotIn("NEVER_SERIALIZE", text)
            self.assertNotIn("private-endpoint", text)
            failed = [record for record in records if record["status"] == "request_failed"]
            self.assertEqual(1, len(failed))
            self.assertEqual("RuntimeError", failed[0]["error_type"])

    def test_unknown_condition_duplicate_request_and_changed_input_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.collection(folder)
            original = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            for mutate in (lambda rows: rows.append(deepcopy(rows[1])),
                           lambda rows: rows[1].update(condition="C"),
                           lambda rows: rows[1]["input"].update(self_report="changed"),
                           lambda rows: rows[1]["model_metadata"].update(model="different"),
                           lambda rows: rows[1]["output"].update(explanation="changed")):
                rows = deepcopy(original)
                mutate(rows)
                path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
                with self.assertRaises(compare.EvaluationError):
                    compare.load_collection(path, self.dataset, self.dataset_hash)

    def test_interrupted_collection_reports_missing_not_failed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.collection(folder)
            lines = path.read_text(encoding="utf-8").splitlines()
            path.write_text("\n".join(lines[:-1]), encoding="utf-8")
            _, records, completeness = compare.load_collection(path, self.dataset, self.dataset_hash)
            self.assertEqual(3, len(records))
            self.assertEqual(1, completeness["missing"])

    def test_blinded_material_hides_condition_model_and_node_ids_reproducibly(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.collection(folder)
            destinations = [Path(folder) / name for name in ("first", "second")]
            for destination in destinations:
                destination.mkdir()
                review.blind(path, destination, self.dataset, self.dataset_hash, 99)
            first = json.loads((destinations[0] / "anonymous-review.json").read_text(encoding="utf-8"))
            second = json.loads((destinations[1] / "anonymous-review.json").read_text(encoding="utf-8"))
            self.assertEqual(first, second)
            self.assertNotIn("selected-model-fixture", json.dumps(first))
            self.assertEqual(4, len(first["items"]))
            for item in first["items"]:
                self.assertNotIn("condition", item)
                self.assertNotIn("focus_node_id", item["response"])
                self.assertTrue(all(score is None for score in item["review"]["scores"].values()))

    def test_empty_human_scores_stay_missing_and_no_fake_improvement(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.collection(folder)
            destination = Path(folder) / "blind"
            destination.mkdir()
            review.blind(path, destination, self.dataset, self.dataset_hash, 99)
            summary = review.summarize(path, destination / "anonymous-review.json", destination / "unblinding-key.json", self.dataset, self.dataset_hash)
            self.assertEqual(0, summary["human_reviewed_outputs"])
            self.assertEqual(0, summary["usable_annotations"])
            for condition in ("A", "B"):
                self.assertEqual(2, summary["conditions"][condition]["unreviewed_successful_outputs"])
                for dimension in compare.DIMENSIONS:
                    self.assertIsNone(summary["conditions"][condition]["dimensions"][dimension]["mean"])
                    self.assertEqual(0, summary["paired_deltas"][dimension]["complete_paired_annotation_count"])
                    self.assertIsNone(summary["paired_deltas"][dimension]["mean_B_minus_A"])

    def test_paired_human_deltas_ties_missing_and_math_error_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.collection(folder)
            destination = Path(folder) / "blind"
            destination.mkdir()
            review.blind(path, destination, self.dataset, self.dataset_hash, 99)
            key = json.loads((destination / "unblinding-key.json").read_text(encoding="utf-8"))
            condition = {item["review_id"]: item["condition"] for item in key["items"]}
            bundle_path = destination / "anonymous-review.json"
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            for item in bundle["items"]:
                human = item["review"]
                human["annotator"] = "Reviewer01"
                human["evidence"] = ["Synthetic evidence, not real model quality scores."]
                human["scores"]["target_match"] = 1
                human["scores"]["action_match"] = 2 if condition[item["review_id"]] == "B" else 1
                human["mathematical_error_count"] = 1 if condition[item["review_id"]] == "A" else 0
                human["mathematical_errors"] = ["Synthetic error"] if condition[item["review_id"]] == "A" else []
            self.save(bundle_path, bundle)
            summary = review.summarize(path, bundle_path, destination / "unblinding-key.json", self.dataset, self.dataset_hash)
            self.assertEqual(2, summary["paired_deltas"]["target_match"]["tie"])
            self.assertEqual(2, summary["paired_deltas"]["action_match"]["B_higher"])
            self.assertEqual(1, summary["paired_deltas"]["action_match"]["mean_B_minus_A"])
            self.assertIsNone(summary["paired_deltas"]["check_quality"]["mean_B_minus_A"])
            self.assertEqual(2, summary["conditions"]["A"]["mathematical_errors"]["sum_reported_errors"])
            self.assertEqual(0, summary["conditions"]["B"]["mathematical_errors"]["sum_reported_errors"])
            # A changed response must invalidate human scoring, even when scores look valid.
            bundle["items"][0]["response"]["explanation"] = "Changed after collection"
            self.save(bundle_path, bundle)
            with self.assertRaises(review.core.EvaluationError):
                review.summarize(path, bundle_path, destination / "unblinding-key.json", self.dataset, self.dataset_hash)

    def test_scores_require_evidence_and_error_count_matches_errors(self):
        human = {"annotator": "Reviewer01", "scores": {key: None for key in compare.DIMENSIONS},
                 "mathematical_error_count": None, "mathematical_errors": [], "evidence": [], "comment": ""}
        human["scores"]["target_match"] = 2
        with self.assertRaises(review.core.EvaluationError):
            review.validate_review(human)
        human["evidence"] = ["Evidence"]
        human["mathematical_error_count"] = 1
        with self.assertRaises(review.core.EvaluationError):
            review.validate_review(human)
        human["mathematical_errors"] = ["Specific error"]
        review.validate_review(human)
        for invalid in (True, 3, -1, 1.0):
            human["scores"]["target_match"] = invalid
            with self.assertRaises(review.core.EvaluationError):
                review.validate_review(human)

    def test_credentials_extra_mapping_fields_cycle_and_hash_drift_rejected(self):
        for mutate in (lambda value: value.update(api_key="secret"),
                       lambda value: value.update(dataset_sha256="0" * 64),
                       lambda value: value["cases"][0]["profiles"][0].update(extra="field"),
                       lambda value: value["cases"][0]["reviewed_graph"]["nodes"][0].update(prerequisite_sets=[["target"]]),
                       lambda value: value["cases"][0]["graph_approval"].update(evidence=["Bearer " + "a" * 40])):
            bad = deepcopy(self.mapping)
            mutate(bad)
            with self.assertRaises(compare.EvaluationError):
                compare.validate_mapping(bad, self.dataset, self.dataset_hash)

    def test_csv_reviews_accept_multiple_annotators_but_reject_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.collection(folder)
            destination = Path(folder) / "blind"
            destination.mkdir()
            review.blind(path, destination, self.dataset, self.dataset_hash, 99)
            csv_path = destination / "anonymous-scores.csv"
            with csv_path.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            rows[0].update(annotator="R01", evidence='["Specific evidence"]', target_match="2")
            extra = dict(rows[0], annotator="R02", target_match="1")
            def write(rows):
                with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.DictWriter(stream, fieldnames=review.SCORE_COLUMNS)
                    writer.writeheader()
                    writer.writerows(rows)
            write(rows + [extra])
            summary = review.summarize(path, csv_path, destination / "unblinding-key.json", self.dataset, self.dataset_hash)
            self.assertEqual(2, summary["usable_annotations"])
            self.assertEqual(1, summary["human_reviewed_outputs"])
            write(rows + [rows[0]])
            with self.assertRaises(review.core.EvaluationError):
                review.summarize(path, csv_path, destination / "unblinding-key.json", self.dataset, self.dataset_hash)

    def test_failed_requests_not_blinded_and_fail_rate_denominator_explicit(self):
        def fail(prompt, **kwargs):
            if "reviewed_graph" in json.loads(prompt):
                raise TimeoutError("not logged")
            return self.generate(prompt, **kwargs)
        with tempfile.TemporaryDirectory() as folder:
            path = self.collection(folder, fail)
            destination = Path(folder) / "blind"
            destination.mkdir()
            review.blind(path, destination, self.dataset, self.dataset_hash, 99)
            summary = review.summarize(path, destination / "anonymous-review.json", destination / "unblinding-key.json", self.dataset, self.dataset_hash)
            self.assertEqual(2, summary["conditions"]["B"]["recorded_requests"])
            self.assertEqual(2, summary["conditions"]["B"]["failed_requests"])
            self.assertEqual(1, summary["conditions"]["B"]["failure_rate_recorded"])
            self.assertEqual(0, summary["conditions"]["B"]["unreviewed_successful_outputs"])

    def test_json_loader_rejects_duplicate_keys_and_nonfinite_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            for text in ('{"schema_version":1,"schema_version":2}', '{"value":NaN}'):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(compare.EvaluationError):
                    compare.load_json(path)

    def test_graph_collection_uses_selected_model_snapshot_not_hardcoded_model(self):
        calls = []
        class FakeGraph:
            study_plan = None
            def model_dump(self):
                return self_graph
        class KnowledgeGraph:
            @staticmethod
            def model_json_schema():
                return {"type": "object"}
            @staticmethod
            def model_validate_json(text):
                return FakeGraph()
        self_graph = self.graph
        def fake_generate(prompt, **kwargs):
            calls.append(kwargs["configuration"])
            return json.dumps(self.graph)
        modules = {
            "graph_builder": SimpleNamespace(GRAPH_INSTRUCTIONS="fixture-instructions", KnowledgeGraph=KnowledgeGraph),
            "llm_client": SimpleNamespace(MODEL="WRONG-HARDCODED-MODEL", generate_text=fake_generate),
            "model_settings": SimpleNamespace(resolve_generation_config=lambda: self.configuration),
        }
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "graphs.jsonl"
            with patch.dict(sys.modules, modules), patch.object(compare.dataset_runner, "output_path", return_value=path), redirect_stdout(io.StringIO()):
                self.assertEqual(0, compare.dataset_runner.collect(self.dataset, self.selected, 2, self.dataset_hash))
            text = path.read_text(encoding="utf-8")
            records = [json.loads(line) for line in text.splitlines()]
            self.assertEqual(2, len(records))
            self.assertEqual([self.configuration, self.configuration], calls)
            self.assertTrue(all(record["model"] == "selected-model-fixture" for record in records))
            self.assertNotIn("WRONG-HARDCODED-MODEL", text)
            self.assertNotIn("private-endpoint", text)
            self.assertNotIn("NEVER_SERIALIZE", text)

    def test_decision_comparison_rejects_graph_answer_leakage(self):
        graph = deepcopy(self.graph)
        graph["study_plan"] = {"mode": "intuition", "objective": "目标", "criteria": ["标准"],
                               "math_context": "共同约定", "diagnostics": [{"reference_answer": "Solved example"}]}
        with self.assertRaises(compare.EvaluationError):
            compare.validate_graph(graph)
        graph["study_plan"]["diagnostics"] = []
        compare.validate_graph(graph)

    def test_collection_rejects_duplicate_json_keys_and_missing_state_field(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.collection(folder)
            original = path.read_text(encoding="utf-8")
            lines = original.splitlines()
            record = json.loads(lines[1])
            lines[1] = '{"condition":"A",' + json.dumps(record, ensure_ascii=False)[1:]
            path.write_text("\n".join(lines), encoding="utf-8")
            with self.assertRaises(compare.EvaluationError):
                compare.load_collection(path, self.dataset, self.dataset_hash)
            lines = original.splitlines()
            record = json.loads(lines[1])
            del record["input"]["self_report"]
            lines[1] = json.dumps(record, ensure_ascii=False)
            path.write_text("\n".join(lines), encoding="utf-8")
            with self.assertRaises(compare.EvaluationError):
                compare.load_collection(path, self.dataset, self.dataset_hash)


if __name__ == "__main__":
    unittest.main()
