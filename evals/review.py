"""Anonymous human review and transparent descriptive summaries; no LLM grader."""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import io
from pathlib import Path
import random

from evals import compare as core

SCORE_COLUMNS = ["review_id", "annotator", *core.DIMENSIONS, "mathematical_error_count", "mathematical_errors", "evidence", "comment"]


def review_payload(record, case, profile, mapping_entry):
    return {"context": core.common_input(case, profile),
            "response": {field: value for field, value in record["output"].items() if field != "focus_node_id"},
            "review_reference": {"expected_concepts": case["expected_concepts"], "pitfalls": case["pitfalls"],
                                 "acceptable_first_steps": profile["acceptable_first_steps"],
                                 "source_sections": case["source_sections"],
                                 "human_reviewed_graph": mapping_entry["reviewed_graph"]}}


def write_blank_plan_csv(path, selected):
    """Named plan sheet is explicitly not the blinded scoring sheet."""
    with Path(path).open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["case_id", "profile_id", "condition", "trial", *SCORE_COLUMNS[1:]])
        writer.writeheader()
        for case in selected:
            for profile in case["profiles"]:
                for condition in ("A", "B"):
                    writer.writerow({"case_id": case["id"], "profile_id": profile["id"], "condition": condition, "trial": 1})


def blind(collection, destination, dataset, dataset_hash, seed):
    header, records, completeness = core.load_collection(collection, dataset, dataset_hash)
    successful = [record for record in records if record["status"] == "collected_unreviewed"]
    random.Random(seed).shuffle(successful)
    collection_hash = core.digest(Path(collection).read_bytes())
    by_case = {case["id"]: case for case in dataset["cases"]}
    mapped = {entry["case_id"]: entry for entry in header["mapping"]["cases"]}
    items, key_items = [], []
    for ordinal, record in enumerate(successful, 1):
        review_id = "R" + core.digest([collection_hash, seed, record["case_id"], record["profile_id"], record["trial"], record["condition"]])[:16]
        case = by_case[record["case_id"]]
        profile = next(profile for profile in case["profiles"] if profile["id"] == record["profile_id"])
        # Both conditions' reviewers see the same mathematical reference context.
        # Node-ID/null would directly reveal graph presence, so omit it in review copies.
        payload = review_payload(record, case, profile, mapped[case["id"]])
        items.append({"review_id": review_id, "display_order": ordinal, **payload,
                      "review": {"annotator": None, "scores": {dimension: None for dimension in core.DIMENSIONS},
                                 "mathematical_error_count": None, "mathematical_errors": [], "evidence": [], "comment": ""}})
        key_items.append({"review_id": review_id, "case_id": record["case_id"], "profile_id": record["profile_id"],
                          "trial": record["trial"], "condition": record["condition"],
                          "output_sha256": record["output_sha256"], "review_payload_sha256": core.digest(payload)})
    core.write_json(destination / "anonymous-review.json", {"schema_version": 1, "collection_sha256": collection_hash,
                    "rubrics": core.RUBRICS, "sources": dataset["sources"], "items": items,
                    "note": "评审材料隐去模型、条件和原始节点 ID；答案文本仍可能泄露条件。空分数不是零分。"})
    core.write_json(destination / "unblinding-key.json", {"schema_version": 1, "collection_sha256": collection_hash,
                    "dataset_sha256": dataset_hash, "seed": seed, "items": key_items,
                    "completeness": completeness, "note": "由协调者保管，评审完成前不交给审阅者。"})
    with (destination / "anonymous-scores.csv").open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=SCORE_COLUMNS)
        writer.writeheader()
        for item in items:
            writer.writerow({"review_id": item["review_id"]})
    return destination


def validate_key(key, collection, header, records, dataset, dataset_hash):
    fields = {"schema_version", "collection_sha256", "dataset_sha256", "seed", "items", "completeness", "note"}
    core.require(isinstance(key, dict) and set(key) == fields and key["schema_version"] == 1 and type(key["seed"]) is int, "Invalid unblinding key")
    core.require(key["collection_sha256"] == core.digest(Path(collection).read_bytes()) and key["dataset_sha256"] == dataset_hash, "Unblinding key collection mismatch")
    lookup = {(record["case_id"], record["profile_id"], record["trial"], record["condition"]): record
              for record in records if record["status"] == "collected_unreviewed"}
    cases = {case["id"]: case for case in dataset["cases"]}
    mappings = {entry["case_id"]: entry for entry in header["mapping"]["cases"]}
    core.require(isinstance(key["items"], list) and len(key["items"]) == len(lookup), "Key does not cover every successful output")
    ids, jobs, result = set(), set(), {}
    for item in key["items"]:
        core.require(isinstance(item, dict) and set(item) == {"review_id", "case_id", "profile_id", "trial", "condition", "output_sha256", "review_payload_sha256"}, "Invalid key entry")
        core.require(all(isinstance(item[field], str) for field in ("review_id", "case_id", "profile_id", "condition")) and type(item["trial"]) is int, "Invalid key identity")
        job = (item["case_id"], item["profile_id"], item["trial"], item["condition"])
        review_id = item["review_id"]
        expected_id = "R" + core.digest([key["collection_sha256"], key["seed"], *job])[:16]
        core.require(job in lookup and job not in jobs and review_id == expected_id and review_id not in ids, "Duplicate, altered or unknown key item")
        case = cases[item["case_id"]]
        profile = next(profile for profile in case["profiles"] if profile["id"] == item["profile_id"])
        expected_payload = review_payload(lookup[job], case, profile, mappings[item["case_id"]])
        core.require(item["output_sha256"] == lookup[job]["output_sha256"] and item["review_payload_sha256"] == core.digest(expected_payload), "Key output or review-content hash mismatch")
        ids.add(review_id)
        jobs.add(job)
        result[review_id] = item
    return result


def text_list(value, *, maximum=30):
    core.require(isinstance(value, list) and len(value) <= maximum and all(isinstance(item, str) and item.strip() and len(item) <= 3000 for item in value), "Invalid human evidence list")
    return value


def validate_review(review):
    core.require(isinstance(review, dict) and set(review) == {"annotator", "scores", "mathematical_error_count", "mathematical_errors", "evidence", "comment"}, "Invalid human review fields")
    core.require(review["annotator"] is None or (isinstance(review["annotator"], str) and review["annotator"].strip() and len(review["annotator"]) <= 80), "Use a short annotator pseudonym")
    scores = review["scores"]
    core.require(isinstance(scores, dict) and set(scores) == set(core.DIMENSIONS), "Invalid review dimensions")
    core.require(all(value is None or (type(value) is int and value in (0, 1, 2)) for value in scores.values()), "Human scores must be missing or 0-2 integers")
    errors = review["mathematical_error_count"]
    core.require(errors is None or (type(errors) is int and 0 <= errors <= 30), "Invalid mathematical error count")
    text_list(review["mathematical_errors"])
    text_list(review["evidence"])
    core.require(isinstance(review["comment"], str) and len(review["comment"]) <= 6000, "Invalid review comment")
    scored = any(value is not None for value in scores.values()) or errors is not None
    if scored:
        core.require(bool(review["annotator"]) and bool(review["evidence"]), "Human scores require annotator and evidence")
    if errors is not None:
        core.require(errors == len(review["mathematical_errors"]), "Mathematical error count must match explicit error evidence")
    core.bounded_tree(review)
    return review


def load_reviews(path, key, dataset, header):
    if Path(path).suffix.lower() == ".csv":
        raw = Path(path).read_bytes()
        core.require(len(raw) <= core.MAX_FILE_BYTES, "Review CSV exceeds size limit")
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        core.require(reader.fieldnames == SCORE_COLUMNS, "Unexpected CSV scoring columns")
        results = []
        for row in reader:
            core.require(None not in row and all(value is not None for value in row.values()), "Malformed CSV review row")
            def integer(value):
                if value == "":
                    return None
                core.require(value.isdigit() and len(value) <= 2, "Invalid integer score")
                return int(value)
            # Use JSON arrays in these CSV cells; no freeform delimiter ambiguity.
            errors = core.json.loads(row["mathematical_errors"]) if row["mathematical_errors"] else []
            evidence = core.json.loads(row["evidence"]) if row["evidence"] else []
            review = {"annotator": row["annotator"] or None,
                      "scores": {dimension: integer(row[dimension]) for dimension in core.DIMENSIONS},
                      "mathematical_error_count": integer(row["mathematical_error_count"]),
                      "mathematical_errors": errors, "evidence": evidence, "comment": row["comment"]}
            results.append((row["review_id"], validate_review(review)))
        core.require(len(results) <= 4000, "Too many review annotations")
        return results
    bundle = core.load_json(path)
    core.require(isinstance(bundle, dict) and set(bundle) == {"schema_version", "collection_sha256", "rubrics", "sources", "items", "note"} and bundle["schema_version"] == 1, "Invalid review bundle")
    core.require(bundle["collection_sha256"] == key["collection_sha256"] and bundle["rubrics"] == core.RUBRICS and bundle["sources"] == dataset["sources"], "Review bundle reference mismatch")
    core.require(isinstance(bundle["items"], list), "Invalid review items")
    lookup = {item["review_id"]: item for item in key["items"]}
    results, seen = [], set()
    for item in bundle["items"]:
        core.require(isinstance(item, dict) and set(item) == {"review_id", "display_order", "context", "response", "review_reference", "review"}, "Invalid review item fields")
        review_id = item["review_id"]
        core.require(isinstance(review_id, str) and review_id in lookup and review_id not in seen, "Unknown or duplicate review item")
        payload = {field: item[field] for field in ("context", "response", "review_reference")}
        core.require(core.digest(payload) == lookup[review_id]["review_payload_sha256"], "Anonymous review content modified")
        results.append((review_id, validate_review(item["review"])))
        seen.add(review_id)
    return results


def summarize(collection, reviews_path, key_path, dataset, dataset_hash):
    header, records, completeness = core.load_collection(collection, dataset, dataset_hash)
    key = core.load_json(key_path)
    key_by_id = validate_key(key, collection, header, records, dataset, dataset_hash)
    reviews = load_reviews(reviews_path, key, dataset, header)
    score_groups = {condition: {dimension: [] for dimension in core.DIMENSIONS} for condition in ("A", "B")}
    math_groups = {condition: [] for condition in ("A", "B")}
    paired, seen, annotated_outputs = {}, set(), set()
    usable_annotations = 0
    for review_id, review in reviews:
        core.require(review_id in key_by_id, "Review references unknown output")
        identity = (review_id, review["annotator"])
        core.require(identity not in seen, "Duplicate output/annotator review")
        seen.add(identity)
        entry = key_by_id[review_id]
        condition = entry["condition"]
        if any(score is not None for score in review["scores"].values()) or review["mathematical_error_count"] is not None:
            usable_annotations += 1
            annotated_outputs.add(review_id)
        for dimension, score in review["scores"].items():
            if score is not None:
                score_groups[condition][dimension].append(score)
                pair = (entry["case_id"], entry["profile_id"], entry["trial"], review["annotator"], dimension)
                paired.setdefault(pair, {})[condition] = score
        if review["mathematical_error_count"] is not None:
            math_groups[condition].append(review["mathematical_error_count"])
    conditions = {}
    for condition in ("A", "B"):
        planned = sum(job[3] == condition for job in header["expected_jobs"])
        current = [record for record in records if record["condition"] == condition]
        successes = sum(record["status"] == "collected_unreviewed" for record in current)
        failures = len(current) - successes
        counts = {dimension: {"valid_annotation_count": len(scores), "distribution": {str(value): scores.count(value) for value in (0, 1, 2)},
                               "mean": sum(scores) / len(scores) if scores else None,
                               "missing_scores_in_submitted_annotations": sum(key_by_id[review_id]["condition"] == condition and review["scores"][dimension] is None for review_id, review in reviews)}
                  for dimension, scores in score_groups[condition].items()}
        conditions[condition] = {"planned_requests": planned, "recorded_requests": len(current), "missing_requests": planned - len(current),
                                 "successful_outputs": successes, "failed_requests": failures,
                                 "failure_rate_recorded": failures / len(current) if current else None,
                                 "unreviewed_successful_outputs": successes - sum(key_by_id[review_id]["condition"] == condition for review_id in annotated_outputs),
                                 "dimensions": counts,
                                 "mathematical_errors": {"valid_annotation_count": len(math_groups[condition]),
                                                          "missing_counts_in_submitted_annotations": sum(key_by_id[review_id]["condition"] == condition and review["mathematical_error_count"] is None for review_id, review in reviews),
                                                          "sum_reported_errors": sum(math_groups[condition]),
                                                          "annotations_with_errors": sum(count > 0 for count in math_groups[condition]),
                                                          "note": "Repeated annotators may flag the same error; totals are annotation counts, not unique errors."}}
    deltas = {}
    for dimension in core.DIMENSIONS:
        pairs = [{"case_id": pair[0], "profile_id": pair[1], "trial": pair[2], "annotator": pair[3],
                  "A": scores["A"], "B": scores["B"], "B_minus_A": scores["B"] - scores["A"]}
                 for pair, scores in paired.items() if pair[-1] == dimension and set(scores) == {"A", "B"}]
        values = [pair["B_minus_A"] for pair in pairs]
        deltas[dimension] = {"complete_paired_annotation_count": len(values), "mean_B_minus_A": sum(values) / len(values) if values else None,
                             "B_higher": sum(value > 0 for value in values), "tie": sum(value == 0 for value in values), "A_higher": sum(value < 0 for value in values),
                             "delta_distribution": {str(value): values.count(value) for value in range(-2, 3)},
                             "unpaired_valid_annotations": sum(1 for pair, scores in paired.items() if pair[-1] == dimension and set(scores) != {"A", "B"}),
                             "pairs": pairs}
    return {"schema_version": 1, "collection_sha256": key["collection_sha256"], "dataset_sha256": dataset_hash,
            "reviews_sha256": core.digest(Path(reviews_path).read_bytes()), "unblinding_key_sha256": core.digest(Path(key_path).read_bytes()),
            "model_metadata": header["model_metadata"], "completeness": completeness, "conditions": conditions,
            "submitted_annotations": len(reviews), "usable_annotations": usable_annotations,
            "human_reviewed_outputs": len(annotated_outputs), "paired_deltas": deltas,
            "claims": "Descriptive human review only. Missing scores are excluded, not zero. No LLM grader, significance claim, or measured learning effect.",
            "scope": "Same-model teaching decisions with versus without human-reviewed structured graph context; graph-generation quality and end-to-end app benefit are separate."}
