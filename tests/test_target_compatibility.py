"""Validation tests for the build-index-compatible target spec.

A target-file typo must fail early and must never silently reduce the
detected target set, so every structural rule of the 39-target registry is
checked here without any live model or C source.
"""

import copy
import json
import unittest
from pathlib import Path

from target_spec import (
    CLOSE_FAMILY,
    COPY_POSITIONS,
    EXPECTED_TARGETS,
    OPEN_FAMILY,
    OPEN_POSITIONS,
    QUEUE_POSITIONS,
    RECORD_OPERATIONS,
    _reject_duplicate_keys,
    load_target_spec,
    spec_digest,
    validate_target_spec,
)

SPEC_PATH = Path(__file__).resolve().parents[1] / "target_specs" / "build_index_targets.json"


class TargetCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = load_target_spec(SPEC_PATH)

    def test_exactly_39_target_names_match_the_registry(self):
        self.assertEqual(len(EXPECTED_TARGETS), 39)
        self.assertEqual(set(self.spec["targets"]), set(EXPECTED_TARGETS))
        self.assertEqual(validate_target_spec(self.spec), [])

    def test_all_argument_indexes_are_positive_1_based_integers(self):
        for name, entry in self.spec["targets"].items():
            for index in entry.get("indices", []):
                self.assertIsInstance(
                    index, int, f"{name}: non-integer index {index!r}"
                )
                self.assertNotIsInstance(index, bool)
                self.assertGreaterEqual(index, 1)

    def test_record_apis_link_to_the_full_open_family(self):
        for name, entry in self.spec["targets"].items():
            if EXPECTED_TARGETS[name] != "record":
                continue
            self.assertEqual(
                sorted(entry["dependent_functions"]), sorted(OPEN_FAMILY),
                f"{name} must keep all four open dependencies",
            )
            self.assertEqual(sorted(entry["close_functions"]), sorted(CLOSE_FAMILY))
            self.assertEqual(entry["handle_index"], 1)
            self.assertEqual(entry["indices"], [])

    def test_open_family_positions_match_the_registry(self):
        for name, (fno_arg, lock_arg) in OPEN_POSITIONS.items():
            entry = self.spec["targets"][name]
            self.assertEqual(entry["indices"], [fno_arg])
            self.assertEqual(entry["discovery"]["lock_arg"], lock_arg)
            self.assertEqual(entry["handle_index"], 1)

    def test_copy_apis_have_the_expected_two_argument_positions(self):
        for name, (source_arg, dest_arg) in COPY_POSITIONS.items():
            entry = self.spec["targets"][name]
            self.assertEqual(sorted(entry["indices"]), sorted((source_arg, dest_arg)))

    def test_queue_and_fork_positions_match_the_registry(self):
        for name, (fno_arg, operation) in QUEUE_POSITIONS.items():
            entry = self.spec["targets"][name]
            self.assertEqual(entry["indices"], [fno_arg])
            self.assertEqual(
                entry["discovery"]["arg_operations"][str(fno_arg)], operation
            )
        for name, family in EXPECTED_TARGETS.items():
            if family == "fork":
                entry = self.spec["targets"][name]
                self.assertEqual(entry["indices"], [1])
                self.assertEqual(
                    entry["discovery"]["arg_operations"]["1"], "FORKPROC"
                )

    def test_reviewed_queue_wrappers_keep_canonical_metadata(self):
        wrapper_positions = {
            "Dac_EnqSem": 2,
            "Dac_EnqSem2": 2,
            "SimEnqueSem": 3,
            "MsgEnqSem": 2,
            "DxiEnqEvent": 2,
            "DxiEnqEvent2": 2,
        }
        for name, index in wrapper_positions.items():
            entry = self.spec["targets"][name]
            self.assertEqual(entry["type"], "QUEUEF")
            self.assertEqual(entry["launch"], "FORK")
            self.assertEqual(entry["indices"], [index])
            self.assertTrue(entry["get_upper"])
            self.assertTrue(entry["semantic_wrapper"])
            self.assertEqual(entry["canonical_target"], "mpf_mfs_addque")

    def test_handle_targets_have_a_valid_handle_index(self):
        for name, entry in self.spec["targets"].items():
            if entry.get("handle_index") is not None:
                self.assertIsInstance(entry["handle_index"], int)
                self.assertGreaterEqual(entry["handle_index"], 1)

    def test_digest_is_stable_and_sensitive_to_target_changes(self):
        first = spec_digest(self.spec)
        self.assertEqual(first, self.spec["digest"])
        self.assertEqual(spec_digest(copy.deepcopy(self.spec)), first)
        changed = copy.deepcopy(self.spec)
        changed["targets"]["mpf_mfs_clearfile"]["indices"] = [2]
        self.assertNotEqual(spec_digest(changed), first)

    def test_duplicate_target_names_fail_early(self):
        text = SPEC_PATH.read_text(encoding="utf-8")
        first_key = next(iter(json.loads(text)["targets"]))
        duplicate_text = text.replace(
            '"targets": {', f'"targets": {{ "{first_key}": {{', 1
        )
        with self.assertRaises(ValueError):
            json.loads(duplicate_text, object_pairs_hook=_reject_duplicate_keys)

    def test_missing_target_is_rejected(self):
        spec = copy.deepcopy(self.spec)
        del spec["targets"]["pmf_forkproc_H"]
        errors = validate_target_spec(spec)
        self.assertIn("missing target: pmf_forkproc_H", errors)

    def test_reduced_open_dependency_list_is_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["targets"]["mpf_mfs_getrec"]["dependent_functions"] = OPEN_FAMILY[:1]
        errors = validate_target_spec(spec)
        self.assertTrue(
            any("dependent_functions must be the full open family" in e for e in errors),
            errors,
        )

    def test_wrong_copy_positions_are_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["targets"]["mpf_mfs_copyrec"]["indices"] = [2, 6]
        errors = validate_target_spec(spec)
        self.assertTrue(
            any("mpf_mfs_copyrec: arguments must be" in e for e in errors), errors
        )

    def test_fixture_spec_without_discovery_metadata_is_not_build_index_valid(self):
        fixture = json.loads(
            (Path(__file__).resolve().parents[1] / "test_scada" / "json_data" / "mpf_data.json").read_text()
        )
        fixture["targets"] = fixture
        errors = validate_target_spec(fixture)
        self.assertTrue(errors)  # scf_* fixture is not the build-index target set


if __name__ == "__main__":
    unittest.main()
