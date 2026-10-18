import random
import unittest

from botc_reasoner.engine import Table
from botc_reasoner.probability import estimate_role_probabilities, joint_assignment_particles
from botc_reasoner.roles import Role
from botc_reasoner.winrate import GameInput, Mind, _info_pair, _sample_historical, estimate_win_rates


def _night_table(roles):
    return Table(
        roles=list(roles),
        alive=[True] * len(roles),
        drunk_mask=None,
        red_herring=None,
        bluffs=(),
        rng=random.Random(0),
        night=2,
        day=1,
        phase="night",
        fixed_registration=True,
    )


class HistoricalKillTests(unittest.TestCase):
    def test_no_death_accepts_a_demon_who_does_not_kill(self):
        roles = [Role.IMP, Role.POISONER, Role.CHEF, Role.EMPATH, Role.VIRGIN]
        chosen = set()
        for seed in range(40):
            table = _night_table(roles)
            choices, _factor = _sample_historical(
                table, 2, tuple(roles), None, [], set(), random.Random(seed),
            )
            chosen.add(choices.imp)
            before = set(table.alive_ids())
            table.resolve_night(choices)
            self.assertEqual(before - set(table.alive_ids()), set())
        self.assertIn(None, chosen)

    def test_no_death_prefers_the_soldier_when_one_is_in_play(self):
        table = _night_table([Role.IMP, Role.POISONER, Role.SOLDIER, Role.CHEF, Role.EMPATH])
        choices, _factor = _sample_historical(
            table, 2, tuple(table.roles), None, [], set(), random.Random(1),
        )
        self.assertEqual(choices.imp, 2)
        before = set(table.alive_ids())
        table.resolve_night(choices)
        self.assertEqual(before - set(table.alive_ids()), set())

    def test_fortune_reuses_a_player_in_a_new_pair_only(self):
        table = _night_table(
            [Role.FORTUNE_TELLER, Role.CHEF, Role.EMPATH, Role.IMP, Role.POISONER]
        )
        mind = Mind(0, Role.FORTUNE_TELLER)
        mind.info_uses[(1, 2)] = 1
        probs = [{Role.CHEF: 1.0} for _ in range(table.n)]
        first = _info_pair(table, mind, probs, random.Random(0))
        self.assertEqual(first, (1, 3))
        seen = {first}
        while True:
            nxt = _info_pair(table, mind, probs, random.Random(0))
            if nxt is None:
                break
            seen.add(nxt)
        self.assertNotIn((1, 2), seen)
        self.assertEqual(mind.info_uses[(1, 2)], 1)

    def test_two_deaths_in_one_night_is_impossible(self):
        table = _night_table([Role.IMP, Role.POISONER, Role.SOLDIER, Role.CHEF, Role.EMPATH])
        self.assertIsNone(
            _sample_historical(table, 2, tuple(table.roles), None, [], {2, 3}, random.Random(0))
        )


class JointSampleTests(unittest.TestCase):
    def test_particles_match_the_marginal_estimate(self):
        kwargs = dict(
            n_players=5,
            counts=(3, 0, 1, 1),
            seed=3,
            target_accepted=400,
            max_trials=400,
        )
        marginals = estimate_role_probabilities(**kwargs)
        particles = joint_assignment_particles(**kwargs)
        self.assertIsNotNone(marginals)
        self.assertIsNotNone(particles)
        assert marginals is not None and particles is not None
        total = sum(weight for _bag, weight, _trusted in particles)
        imp = [0.0] * 5
        for bag, weight, _trusted in particles:
            for player, role in enumerate(bag):
                if role is Role.IMP:
                    imp[player] += weight / total
        for player in range(5):
            self.assertAlmostEqual(imp[player], marginals[player].get(Role.IMP, 0.0))


class WinRateTests(unittest.TestCase):
    def test_day_one_returns_a_distribution(self):
        state = GameInput.from_dict(
            {
                "n_players": 5,
                "counts": [3, 0, 1, 1],
                "phase": "day",
                "day": 1,
                "propositions": [
                    {"reliable": False, "kind": "role", "player": 0, "role": "slayer"}
                ],
            }
        )
        result = estimate_win_rates(
            state,
            samples=1,
            seed=1,
            horizon=3,
            attempts=8,
            agent_samples=1,
            agent_trials=6,
        )
        self.assertGreater(result.samples, 0)
        self.assertAlmostEqual(result.good + result.evil, 1.0)
        self.assertGreaterEqual(result.good, 0.0)
        self.assertGreaterEqual(result.evil, 0.0)

    def test_parallel_worlds_match_one_process(self):
        import botc_reasoner.winrate as winrate_module

        state = GameInput.from_dict(
            {
                "n_players": 5,
                "counts": [3, 0, 1, 1],
                "phase": "day",
                "day": 1,
                "propositions": [
                    {"reliable": False, "kind": "role", "player": 0, "role": "chef"},
                    {"reliable": False, "kind": "role", "player": 1, "role": "empath"},
                    {"reliable": False, "kind": "role", "player": 2, "role": "fortune_teller"},
                ],
            }
        )
        kwargs = dict(samples=2, seed=1, horizon=2, attempts=4, agent_samples=2, agent_trials=4)
        original = winrate_module.worker_count
        winrate_module.worker_count = lambda ntasks, requested=None: 1
        try:
            sequential = estimate_win_rates(state, **kwargs)
        finally:
            winrate_module.worker_count = original
        parallel = estimate_win_rates(state, **kwargs)
        self.assertEqual(sequential, parallel)


if __name__ == "__main__":
    unittest.main()
