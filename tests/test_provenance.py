"""规则来源追踪（``botc_reasoner.provenance`` 与 ``rules.collect_game_rules``）测试。

覆盖：收集器的 add/展平、rule context 的进入与恢复、元数据登记与冲突，
以及与普通 ``Solver`` 求解路径的约束一致性（5 人 1 夜）。
"""

import unittest
from collections import Counter

from z3 import BoolVal, Solver, sat

from botc_reasoner import declare_variables
from botc_reasoner.provenance import (
    UNCLASSIFIED_RULE_ID,
    ConstraintCollector,
    RuleSpec,
    rule_context,
)
from botc_reasoner.roles import BASE_SETUP
from botc_reasoner.rules import WIKI_URL, add_game_rules, collect_game_rules


class CollectorAddAndFlattenTests(unittest.TestCase):
    def test_add_flattens_nested_sequences(self):
        collector = ConstraintCollector()
        a, b, c = BoolVal(True), BoolVal(False), BoolVal(True)
        collector.add([a, (b, [c])])
        self.assertEqual([record.expr for record in collector.records], [a, b, c])

    def test_python_bool_becomes_boolval(self):
        collector = ConstraintCollector()
        collector.add(True)
        self.assertEqual(collector.records[0].expr, BoolVal(True))

    def test_records_carry_unique_instance_ids(self):
        collector = ConstraintCollector()
        collector.add(BoolVal(True), BoolVal(False))
        ids = [record.instance_id for record in collector.records]
        self.assertEqual(ids, ["tb:unclassified#1", "tb:unclassified#2"])
        self.assertEqual(len(ids), len(set(ids)))


class RuleContextTests(unittest.TestCase):
    def test_context_restores_outer_after_exit(self):
        collector = ConstraintCollector()
        with collector.context("outer", title="外"):
            collector.add(BoolVal(True))
            with collector.context("inner", title="内"):
                collector.add(BoolVal(True))
            collector.add(BoolVal(True))
        collector.add(BoolVal(True))
        self.assertEqual(
            [record.rule_id for record in collector.records],
            ["outer", "inner", "outer", UNCLASSIFIED_RULE_ID],
        )

    def test_rule_context_is_noop_without_context_attribute(self):
        solver = Solver()
        with rule_context(solver, "tb:setup", "开局配置", source=WIKI_URL):
            solver.add(BoolVal(True))
        self.assertEqual(solver.check(), sat)


class MetadataTests(unittest.TestCase):
    def test_conflicting_metadata_is_rejected(self):
        collector = ConstraintCollector()
        collector.register(RuleSpec(id="tb:x", title="甲"))
        with self.assertRaises(ValueError):
            collector.register(RuleSpec(id="tb:x", title="乙"))

    def test_empty_fields_are_filled_in(self):
        collector = ConstraintCollector()
        collector.register(RuleSpec(id="tb:x", title="甲"))
        merged = collector.register(RuleSpec(id="tb:x", title="", source=WIKI_URL))
        self.assertEqual(merged.title, "甲")
        self.assertEqual(merged.source, WIKI_URL)

    def test_catalog_keeps_single_entry_per_id(self):
        collector = ConstraintCollector()
        with collector.context("tb:x", title="甲", source=WIKI_URL):
            collector.add(BoolVal(True))
        with collector.context("tb:x", title="甲", source=WIKI_URL):
            collector.add(BoolVal(False))
        self.assertEqual(list(collector.catalog).count("tb:x"), 1)
        self.assertEqual(collector.catalog["tb:x"].title, "甲")


class GameRulesConsistencyTests(unittest.TestCase):
    """5 人 1 夜：普通 Solver 与收集器的约束多重集必须一致。"""

    def _solver_exprs(self):
        world = declare_variables(5, n_nights=1, tag="prov")
        solver = Solver()
        add_game_rules(solver, world, *BASE_SETUP[5])
        return Counter(assertion.sexpr() for assertion in solver.assertions())

    def _collector(self):
        world = declare_variables(5, n_nights=1, tag="prov")
        return world, collect_game_rules(world, *BASE_SETUP[5])

    def test_collector_matches_plain_solver_constraints(self):
        _, collector = self._collector()
        collected = Counter(record.expr.sexpr() for record in collector.records)
        self.assertEqual(collected, self._solver_exprs())

    def test_collected_constraints_are_satisfiable(self):
        world, collector = self._collector()
        solver = world.build_solver()
        for record in collector.records:
            solver.add(record.expr)
        self.assertEqual(solver.check(), sat)

    def test_no_unclassified_records(self):
        _, collector = self._collector()
        self.assertFalse(
            [record for record in collector.records if record.rule_id == UNCLASSIFIED_RULE_ID]
        )

    def test_instance_ids_are_unique(self):
        _, collector = self._collector()
        ids = [record.instance_id for record in collector.records]
        self.assertEqual(len(ids), len(set(ids)))

    def test_each_rule_id_has_single_catalog_entry(self):
        _, collector = self._collector()
        ids = [record.rule_id for record in collector.records]
        for rule_id in set(ids):
            self.assertIn(rule_id, collector.catalog)
        self.assertEqual(len(collector.catalog), len(set(collector.catalog)))

    def test_expected_rule_ids_are_registered(self):
        _, collector = self._collector()
        expected = {
            "tb:setup",
            "tb:opening",
            "tb:poison_drunk",
            "tb:continuity",
            "tb:night_kills",
            "tb:day_rules",
            "tb:information",
            "tb:votes_virgin",
            "tb:slayer",
            "tb:butler",
        }
        self.assertTrue(expected.issubset(collector.catalog))
        for spec in collector.catalog.values():
            if spec.id != UNCLASSIFIED_RULE_ID:
                self.assertEqual(spec.source, WIKI_URL)


if __name__ == "__main__":
    unittest.main()
