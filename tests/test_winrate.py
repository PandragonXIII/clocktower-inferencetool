import unittest

from botc_reasoner.probability import estimate_role_probabilities, joint_assignment_particles
from botc_reasoner.roles import Role
from botc_reasoner.winrate import GameInput, estimate_win_rates


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
