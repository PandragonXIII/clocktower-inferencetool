import math
import random
import unittest

from z3 import And, Bool, Not, unsat

from botc_reasoner import Ability, Role, add_game_rules, declare_variables, estimate_role_probabilities
from botc_reasoner.probability import (
    EVIL_CLAIM_MISMATCH,
    GOOD_CLAIM_MISMATCH,
    AbilityObservation,
    _ability_option_count,
    _claim_weight,
    _credibility_groups,
    _info_multiplier,
    _interference_factor,
    draw_setup,
)
from test_reasoning import _parse_fact, _parse_facts, _reason


class SetupPriorTests(unittest.TestCase):
    def test_draw_keeps_a_legal_bag(self):
        rng = random.Random(0)
        for _ in range(200):
            drawn = draw_setup(rng, 8, (5, 1, 1, 1))
            self.assertIsNotNone(drawn)
            assert drawn is not None
            bag, mask = drawn
            self.assertEqual(len(bag), 8)
            self.assertEqual(len(set(bag)), 8)
            self.assertEqual(bag.count(Role.IMP), 1)
            if Role.BARON in bag:
                self.assertEqual(sum(role in _OUTSIDERS for role in bag), 3)
                self.assertEqual(sum(role in _TOWNSFOLK for role in bag), 3)
            else:
                self.assertEqual(sum(role in _OUTSIDERS for role in bag), 1)
                self.assertEqual(sum(role in _TOWNSFOLK for role in bag), 5)
            self.assertIsNone(mask)

    def test_each_seat_has_the_same_demon_prior(self):
        probabilities = estimate_role_probabilities(
            5,
            (3, 0, 1, 1),
            seed=1,
            target_accepted=3000,
            max_trials=3000,
        )
        self.assertIsNotNone(probabilities)
        assert probabilities is not None
        self.assertAlmostEqual(sum(item.get(Role.IMP, 0.0) for item in probabilities), 1.0, delta=0.04)
        for item in probabilities:
            self.assertAlmostEqual(item.get(Role.IMP, 0.0), 0.2, delta=0.04)
            self.assertAlmostEqual(item.get(Role.BARON, 0.0), 0.05, delta=0.03)

    def test_own_token_leaves_only_that_role_or_the_drunk(self):
        probabilities = estimate_role_probabilities(
            5,
            (3, 0, 1, 1),
            beliefs=[(0, Role.FORTUNE_TELLER)],
            seed=2,
            target_accepted=1500,
            max_trials=80_000,
        )
        self.assertIsNotNone(probabilities)
        assert probabilities is not None
        own = probabilities[0]
        self.assertGreater(own.get(Role.FORTUNE_TELLER, 0.0), 0.5)
        self.assertGreater(own.get(Role.DRUNK, 0.0), 0.03)
        self.assertLess(own[Role.DRUNK], own[Role.FORTUNE_TELLER])
        self.assertNotIn(Role.IMP, own)

    def test_good_claim_is_penalized_and_evil_claim_is_not(self):
        good_lie = (Role.CHEF, Role.EMPATH, Role.FORTUNE_TELLER, Role.UNDERTAKER, Role.SAINT, Role.POISONER, Role.IMP, Role.VIRGIN)
        evil_lie = (Role.CHEF, Role.EMPATH, Role.FORTUNE_TELLER, Role.UNDERTAKER, Role.SAINT, Role.INVESTIGATOR, Role.POISONER, Role.IMP)
        drunk_match = (Role.CHEF, Role.EMPATH, Role.FORTUNE_TELLER, Role.UNDERTAKER, Role.DRUNK, Role.POISONER, Role.IMP, Role.VIRGIN)
        self.assertEqual(_claim_weight(good_lie, None, [(0, Role.WASHERWOMAN)]), GOOD_CLAIM_MISMATCH)
        self.assertAlmostEqual(_claim_weight(evil_lie, None, [(7, Role.WASHERWOMAN)]), EVIL_CLAIM_MISMATCH)
        self.assertEqual(_claim_weight(drunk_match, Role.WASHERWOMAN, [(4, Role.WASHERWOMAN)]), 1.0)
        self.assertEqual(_claim_weight(drunk_match, Role.CHEF, [(4, Role.WASHERWOMAN)]), GOOD_CLAIM_MISMATCH)
        self.assertEqual(_claim_weight(drunk_match, Role.CHEF, [(4, Role.IMP)]), GOOD_CLAIM_MISMATCH)
        self.assertEqual(_claim_weight(drunk_match, Role.CHEF, [(4, Role.SAINT)]), GOOD_CLAIM_MISMATCH)
        self.assertEqual(_claim_weight(drunk_match, Role.CHEF, [(4, Role.DRUNK)]), 1.0)

    def test_another_players_claim_raises_that_role_without_making_it_certain(self):
        claimed = estimate_role_probabilities(
            5,
            (3, 0, 1, 1),
            soft_roles=[(1, Role.WASHERWOMAN)],
            seed=3,
            target_accepted=2000,
            max_trials=20000,
        )
        self.assertIsNotNone(claimed)
        assert claimed is not None
        self.assertGreater(claimed[1].get(Role.WASHERWOMAN, 0.0), 0.5)
        self.assertLess(claimed[1].get(Role.IMP, 0.0), 0.05)

    def test_ignored_skill_divides_group_weight_by_its_options(self):
        observations = [AbilityObservation(0, Ability.INVESTIGATOR, 1, Bool("investigator_ping"))]
        claims = [
            (0, Role.INVESTIGATOR),
            (1, Role.SOLDIER),
            (2, Role.CHEF),
            (3, Role.EMPATH),
        ]
        groups = _credibility_groups(5, (3, 0, 1, 1), claims, observations)
        ignored_weight = {}
        for trusted, weight in groups:
            trusted_players = {player for player, _role in trusted}
            ignored = [player for player, _role in claims if player not in trusted_players]
            if len(ignored) == 1:
                ignored_weight[ignored[0]] = weight
        options = _ability_option_count(Ability.INVESTIGATOR, 5)
        self.assertEqual(options, 40)
        self.assertAlmostEqual(ignored_weight[1] / ignored_weight[0], 1 / _info_multiplier(options))
        self.assertAlmostEqual(_info_multiplier(options), 1 / (1 + math.log2(40)))
        self.assertAlmostEqual(_info_multiplier(9), 1 / (1 + math.log2(9)))
        self.assertNotAlmostEqual(_info_multiplier(9), _info_multiplier(3) ** 2)
        self.assertAlmostEqual(ignored_weight[1], (0.7 ** 3) * 0.3)

    def test_poison_that_voids_a_reading_divides_the_sample_by_good_count(self):
        world = declare_variables(5, n_nights=1, tag="poison_factor")
        solver = world.build_solver()
        add_game_rules(solver, world, 3, 0, 1, 1)
        claim = And(
            world.fortune_first[1][0][1],
            world.fortune_second[1][0][2],
            Not(world.fortune_yes[1][0]),
        )
        observation = AbilityObservation(0, Ability.FORTUNE_TELLER, 1, claim)
        poisoned = (
            Role.FORTUNE_TELLER,
            Role.IMP,
            Role.CHEF,
            Role.EMPATH,
            Role.POISONER,
        )
        sober = (
            Role.FORTUNE_TELLER,
            Role.CHEF,
            Role.EMPATH,
            Role.POISONER,
            Role.IMP,
        )
        common = dict(
            beliefs=[(0, Role.FORTUNE_TELLER)],
            trusted_claims=[(0, Role.FORTUNE_TELLER)],
            soft_abilities=[observation],
        )
        night_options = _ability_option_count(Ability.FORTUNE_TELLER, 5)
        utterance = _info_multiplier(night_options)
        self.assertAlmostEqual(_interference_factor(solver, world, poisoned, **common), utterance / 3)
        self.assertAlmostEqual(_interference_factor(solver, world, sober, **common), 1 / 3)

    def test_poison_divisor_counts_only_good_players_alive_that_night(self):
        world = declare_variables(5, n_nights=2, tag="poison_alive")
        solver = world.build_solver()
        add_game_rules(solver, world, 3, 0, 1, 1)
        claim = And(
            world.fortune_first[2][0][1],
            world.fortune_second[2][0][2],
            Not(world.fortune_yes[2][0]),
        )
        solver.add(Not(world.alive_night_start[2][2]))
        bag = (
            Role.FORTUNE_TELLER,
            Role.IMP,
            Role.CHEF,
            Role.EMPATH,
            Role.POISONER,
        )
        factor = _interference_factor(
            solver,
            world,
            bag,
            beliefs=[(0, Role.FORTUNE_TELLER)],
            trusted_claims=[(0, Role.FORTUNE_TELLER)],
            soft_abilities=[AbilityObservation(0, Ability.FORTUNE_TELLER, 2, claim)],
        )
        self.assertAlmostEqual(factor, _info_multiplier(_ability_option_count(Ability.FORTUNE_TELLER, 5)) / 2)

    def test_drunk_voids_every_night_with_one_info_multiplier(self):
        world = declare_variables(5, n_nights=2, tag="drunk_factor")
        solver = world.build_solver()
        add_game_rules(solver, world, 3, 0, 1, 1)
        first = And(
            world.fortune_first[1][0][1],
            world.fortune_second[1][0][2],
            Not(world.fortune_yes[1][0]),
        )
        second = And(
            world.fortune_first[2][0][1],
            world.fortune_second[2][0][3],
            Not(world.fortune_yes[2][0]),
        )
        bag = (Role.DRUNK, Role.IMP, Role.CHEF, Role.EMPATH, Role.POISONER)
        factor = _interference_factor(
            solver,
            world,
            bag,
            beliefs=[(0, Role.FORTUNE_TELLER)],
            trusted_claims=[(0, Role.FORTUNE_TELLER)],
            soft_abilities=[
                AbilityObservation(0, Ability.FORTUNE_TELLER, 1, first),
                AbilityObservation(0, Ability.FORTUNE_TELLER, 2, second),
            ],
        )
        one_night = _ability_option_count(Ability.FORTUNE_TELLER, 5)
        self.assertAlmostEqual(factor, _info_multiplier(one_night * one_night))
        self.assertNotAlmostEqual(factor, _info_multiplier(one_night) ** 2)

    def test_healthy_pair_info_pays_for_the_decoy_and_which_role(self):
        world = declare_variables(5, n_nights=1, tag="decoy_factor")
        solver = world.build_solver()
        add_game_rules(solver, world, 3, 0, 1, 1)
        washerwoman = And(
            world.washerwoman_role[0][Role.EMPATH],
            world.washerwoman_first[0][1],
            world.washerwoman_second[0][2],
        )
        bag = (Role.WASHERWOMAN, Role.EMPATH, Role.CHEF, Role.POISONER, Role.IMP)
        factor = _interference_factor(
            solver,
            world,
            bag,
            beliefs=[(0, Role.WASHERWOMAN)],
            trusted_claims=[(0, Role.WASHERWOMAN)],
            soft_abilities=[AbilityObservation(0, Ability.WASHERWOMAN, 1, washerwoman)],
        )
        self.assertAlmostEqual(factor, _info_multiplier((5 - 1) * 3))
        librarian = world.librarian_none[0]
        none_bag = (Role.LIBRARIAN, Role.CHEF, Role.EMPATH, Role.POISONER, Role.IMP)
        none_factor = _interference_factor(
            solver,
            world,
            none_bag,
            beliefs=[(0, Role.LIBRARIAN)],
            trusted_claims=[(0, Role.LIBRARIAN)],
            soft_abilities=[AbilityObservation(0, Ability.LIBRARIAN, 1, librarian)],
        )
        self.assertEqual(none_factor, 1.0)

    def test_red_herring_fraction_is_lower_when_the_yes_is_not_the_demon(self):
        world = declare_variables(5, n_nights=1, tag="red_herring_factor")
        solver = world.build_solver()
        add_game_rules(solver, world, 3, 0, 1, 1)
        claim = And(
            world.fortune_first[1][0][1],
            world.fortune_second[1][0][2],
            world.fortune_yes[1][0],
        )
        common = dict(
            beliefs=[(0, Role.FORTUNE_TELLER)],
            trusted_claims=[(0, Role.FORTUNE_TELLER)],
            soft_abilities=[AbilityObservation(0, Ability.FORTUNE_TELLER, 1, claim)],
        )
        demon_in_pair = (
            Role.FORTUNE_TELLER,
            Role.IMP,
            Role.CHEF,
            Role.EMPATH,
            Role.POISONER,
        )
        herring_only = (
            Role.FORTUNE_TELLER,
            Role.CHEF,
            Role.EMPATH,
            Role.POISONER,
            Role.IMP,
        )
        self.assertAlmostEqual(_interference_factor(solver, world, demon_in_pair, **common), 1.0)
        self.assertAlmostEqual(_interference_factor(solver, world, herring_only, **common), 2 / 3)

    def test_specific_info_keeps_its_group_weight_when_rejection_misses(self):
        world = declare_variables(5, n_nights=2, tag="specific_keep")
        solver = world.build_solver()
        add_game_rules(solver, world, 3, 0, 1, 1)
        claim = And(
            world.investigator_role[0][Role.POISONER],
            world.investigator_first[0][1],
            world.investigator_second[0][2],
        )
        probabilities = estimate_role_probabilities(
            5,
            (3, 0, 1, 1),
            soft_roles=[(0, Role.INVESTIGATOR)],
            soft_abilities=[AbilityObservation(0, Ability.INVESTIGATOR, 1, claim)],
            solver=solver,
            world=world,
            seed=4,
            target_accepted=8,
            max_trials=0,
        )
        self.assertIsNotNone(probabilities)
        assert probabilities is not None
        own = probabilities[0]
        self.assertGreater(own.get(Role.INVESTIGATOR, 0.0), 0.5)
        self.assertLess(own.get(Role.IMP, 0.0), 0.05)
        self.assertAlmostEqual(sum(own.values()), 1.0, delta=1e-9)

    def test_poisoner_poisons_at_most_one_player_per_night(self):
        world = declare_variables(5, n_nights=2, tag="poison_once")
        solver = world.build_solver()
        add_game_rules(solver, world, 3, 0, 1, 1)
        solver.add(world.start_is(0, Role.POISONER))
        solver.add(world.poisoned[1][1], world.poisoned[1][2])
        self.assertEqual(solver.check(), unsat)


class InputFormatTests(unittest.TestCase):
    def test_own_claim_and_public_fact_are_distinguished(self):
        _nights, statements = _parse_facts(
            [
                "我是 1 占卜师",
                "自认 1 占卜师",
                "自称 2 洗衣妇",
                "夜间死亡 2夜 3",
                "无人死亡 3夜",
                "夜间死亡 3夜 无",
                "处决 1天 4",
                "无人处决 1天",
                "处决 2天 无",
                "我发动 1夜 1 占卜师 2 3 否",
                "自称发动 1夜 2 洗衣妇 厨师 3 4",
                "自称发动 1天 2 猎手 1",
            ],
            5,
        )
        self.assertEqual(statements[0].pin, "belief")
        self.assertTrue(statements[0].setup_only)
        self.assertEqual(statements[1].pin, "belief")
        self.assertEqual(statements[2].mode, "soft_role")
        self.assertTrue(statements[3].mode == "hard" and not statements[3].setup_only)
        self.assertTrue(statements[4].mode == "hard" and not statements[4].setup_only)
        self.assertTrue(statements[5].mode == "hard" and not statements[5].setup_only)
        self.assertTrue(statements[6].mode == "hard" and not statements[6].setup_only)
        self.assertTrue(statements[7].mode == "hard" and not statements[7].setup_only)
        self.assertTrue(statements[8].mode == "hard" and not statements[8].setup_only)
        self.assertEqual(statements[9].mode, "hard")
        self.assertEqual(statements[9].ability.name, "FORTUNE_TELLER")
        self.assertEqual(statements[10].mode, "soft_ability")
        self.assertEqual(statements[11].mode, "hard")
        self.assertEqual(statements[11].ability.name, "SLAYER")

    def test_bare_activation_is_rejected(self):
        with self.assertRaises(ValueError):
            _parse_fact("发动 1夜 1 厨师 0", 5)

    def test_nobody_died_is_accepted_and_blocks_a_free_night_kill(self):
        from z3 import Not, sat

        world = declare_variables(5, n_nights=2, tag="nobody_died")
        solver = world.build_solver()
        add_game_rules(solver, world, 3, 0, 1, 1)
        _nights, statements = _parse_facts(["无人死亡 2夜"], 5)
        solver.add(statements[0].build(world))
        self.assertEqual(solver.check(), sat)

        killed = declare_variables(5, n_nights=2, tag="must_kill")
        must = killed.build_solver()
        add_game_rules(must, killed, 3, 0, 1, 1)
        roles = [Role.IMP, Role.POISONER, Role.CHEF, Role.EMPATH, Role.FORTUNE_TELLER]
        for player, role in enumerate(roles):
            must.add(killed.start_is(player, role))
            must.add(killed.alive_night_start[2][player])
        must.add(Not(killed.is_droisoned(0, 2)))
        for player in killed.player_ids:
            must.add(Not(killed.night_death[2][player]))
        self.assertEqual(must.check(), unsat)

        freed = declare_variables(8, n_nights=2, tag="ft_killed_freely")
        free = freed.build_solver()
        add_game_rules(free, freed, 5, 1, 1, 1)
        bag = (
            Role.CHEF,
            Role.EMPATH,
            Role.FORTUNE_TELLER,
            Role.UNDERTAKER,
            Role.IMP,
            Role.SPY,
            Role.DRUNK,
            Role.SOLDIER,
        )
        for player, role in enumerate(bag):
            free.add(freed.start_is(player, role))
        free.add(freed.drunk_mask[Role.WASHERWOMAN])
        free.add(
            And(
                freed.fortune_first[2][2][3],
                freed.fortune_second[2][2][4],
                Not(freed.fortune_yes[2][2]),
            )
        )
        self.assertEqual(free.check(), sat)
        free.add(freed.alive_night_start[2][2])
        for player in freed.player_ids:
            free.add(Not(freed.night_death[2][player]))
        self.assertEqual(free.check(), unsat)

    def test_nobody_executed_is_accepted_and_blocks_a_free_day_execution(self):
        from z3 import Not, sat

        world = declare_variables(5, n_nights=2, tag="nobody_executed")
        solver = world.build_solver()
        add_game_rules(solver, world, 3, 0, 1, 1)
        _nights, statements = _parse_facts(["无人处决 1天", "处决 1天 无"], 5)
        solver.add(statements[0].build(world))
        self.assertEqual(solver.check(), sat)
        solver.add(world.executed[1][0])
        self.assertEqual(solver.check(), unsat)

        freed = declare_variables(8, n_nights=2, tag="ft_executed_freely")
        free = freed.build_solver()
        add_game_rules(free, freed, 5, 1, 1, 1)
        bag = (
            Role.CHEF,
            Role.EMPATH,
            Role.FORTUNE_TELLER,
            Role.UNDERTAKER,
            Role.IMP,
            Role.SPY,
            Role.DRUNK,
            Role.SOLDIER,
        )
        for player, role in enumerate(bag):
            free.add(freed.start_is(player, role))
        free.add(freed.drunk_mask[Role.WASHERWOMAN])
        free.add(
            And(
                freed.fortune_first[2][2][3],
                freed.fortune_second[2][2][4],
                Not(freed.fortune_yes[2][2]),
            )
        )
        for player in freed.player_ids:
            free.add(Not(freed.night_death[2][player]))
        self.assertEqual(free.check(), sat)
        _nights, statements = _parse_facts(["无人处决 1天"], 8)
        free.add(statements[0].build(freed))
        self.assertEqual(free.check(), unsat)

    def test_public_death_and_own_token_show_probabilities(self):
        nights, statements = _parse_facts(["我是 1 占卜师", "自称 2 洗衣妇"], 5)
        lines = _reason((3, 0, 1, 1), nights, statements)
        self.assertIsNotNone(lines)
        assert lines is not None
        self.assertNotIn("存在矛盾", lines[0])
        own = next(line for line in lines if line.startswith("玩家 1："))
        self.assertIn("占卜师", own)
        self.assertIn("%", own)
        self.assertNotIn("小恶魔", own)
        other = next(line for line in lines if line.startswith("玩家 2："))
        self.assertIn("洗衣妇", other)
        self.assertIn("%", other)


_TOWNSFOLK = {
    Role.WASHERWOMAN,
    Role.LIBRARIAN,
    Role.INVESTIGATOR,
    Role.CHEF,
    Role.EMPATH,
    Role.FORTUNE_TELLER,
    Role.UNDERTAKER,
    Role.MONK,
    Role.RAVENKEEPER,
    Role.VIRGIN,
    Role.SLAYER,
    Role.SOLDIER,
    Role.MAYOR,
}
_OUTSIDERS = {Role.BUTLER, Role.DRUNK, Role.RECLUSE, Role.SAINT}


if __name__ == "__main__":
    unittest.main()
