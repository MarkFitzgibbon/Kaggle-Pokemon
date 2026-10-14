import copy
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from battle_logging import MatchLogger, record_decision_details, split_games


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def observation(player=0, game=1):
    return {"select": {"option": [{"name": "attack"}, {"name": "pass"}], "minCount": 1, "maxCount": 1},
            "current": {"yourIndex": player, "round": game, "turn": 2},
            "search_begin_input": "opaque-engine-snapshot"}


def pick(obs):
    return [0]


class FakeEnv:
    def __init__(self):
        self.steps = [[{"status": "ACTIVE", "reward": 0}, {"status": "INACTIVE", "reward": 0}]]
        self.logs = []
        self.configuration = {"bo": 3}
        self.specification = SimpleNamespace(version="test")
        self.done = False

    def advance(self, final=False):
        self.steps.append([{"status": "DONE" if final else "ACTIVE", "reward": 1 if final else 0},
                           {"status": "DONE" if final else "INACTIVE", "reward": -1 if final else 0}])
        self.done = final

    def toJSON(self):
        return {"steps": copy.deepcopy(self.steps)}

    def render(self, **kwargs):
        return json.dumps(kwargs["environment"])


class MatchLoggingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.logger = MatchLogger(self.temp.name, [pick, pick], ["A", "B"], 42, {"bo": 3})
        self.env = FakeEnv()

    def test_capture_before_mutation_and_explicit_diagnostics(self):
        def mutating(obs, configuration):
            record_decision_details(scores=[0.9, 0.1], reason="highest score")
            print("model output")
            print("model warning", file=sys.stderr)
            obs["select"]["option"].clear()
            return [0]

        state = observation()
        action = self.logger.wrap_agent(mutating, 0, self.env)(state, {})
        self.assertEqual(action, [0])
        record = read_jsonl(self.logger.game_path(1) / "decisions.jsonl")[0]
        self.assertEqual(record["selected_options"][0]["option"]["name"], "attack")
        self.assertEqual(len(record["observation"]["select"]["option"]), 2)
        self.assertIn("model output", record["stdout"])
        self.assertIn("model warning", record["stderr"])
        self.assertEqual(record["diagnostics"]["reason"], "highest score")

    def test_exception_preserves_input_error_and_partial_training(self):
        def broken(obs):
            raise RuntimeError("model failed")

        with self.assertRaisesRegex(RuntimeError, "model failed"):
            self.logger.wrap_agent(broken, 0, self.env)(observation(), {})
        path = self.logger.game_path(1)
        self.assertEqual(len(read_jsonl(path / "inputs.jsonl")), 1)
        self.assertIn("model failed", (path / "errors.log").read_text())
        summary = self.logger.finalize(self.env, [{"current": {"result": -1, "turn": 2}}], "model failed")
        row = read_jsonl(path / "training.jsonl")[0]
        self.assertTrue(row["truncated"])
        self.assertFalse(row["terminal"])
        self.assertFalse(row["eligible_for_training"])
        self.assertIsNone(row["reward"])
        self.assertEqual(summary["status"], "failed")

    def test_transitions_keep_player_and_game_boundaries(self):
        agents = [self.logger.wrap_agent(pick, player, self.env) for player in (0, 1)]
        for game, player, final in [(1, 0, False), (1, 1, False), (1, 0, False),
                                    (2, 0, False), (2, 1, True)]:
            agents[player](observation(player, game), {})
            self.env.advance(final)
        frames = [{"current": {"result": -1, "turn": 1}}, {"current": {"result": 0, "turn": 3}},
                  {"current": {"result": -1, "turn": 1}}, {"current": {"result": 1, "turn": 4}}]
        self.logger.finalize(self.env, frames)
        first = read_jsonl(self.logger.game_path(1) / "training.jsonl")
        self.assertEqual(first[0]["next_decision_id"], first[2]["decision_id"])
        self.assertEqual(first[0]["next_observation"]["current"]["yourIndex"], 0)
        self.assertTrue(first[1]["terminal"])
        self.assertEqual(first[1]["reward"], -1)
        self.assertTrue(first[2]["terminal"])
        self.assertIsNone(first[2]["next_decision_id"])
        self.assertNotIn("search_begin_input", first[0]["observation"])
        replay = json.loads((self.logger.game_path(2) / "replay.html").read_text())
        self.assertEqual(replay["steps"][0][0]["visualize"], frames[2:])

    def test_invalid_action_is_not_training_eligible(self):
        wrapped = self.logger.wrap_agent(pick, 0, self.env)
        wrapped(observation(), {})
        self.env.advance(True)
        self.env.steps[-1][0]["status"] = "INVALID"
        self.logger.finalize(self.env, [{"current": {"result": -1, "turn": 1}}])
        row = read_jsonl(self.logger.game_path(1) / "training.jsonl")[0]
        self.assertFalse(row["action_applied"])
        self.assertFalse(row["eligible_for_training"])
        self.assertIn("INVALID", (self.logger.game_path(1) / "errors.log").read_text())

    def test_rng_is_per_player_and_restores_caller_state(self):
        def random_agent(obs):
            return [random.randrange(2)]

        state = random.getstate()
        agents = [self.logger.wrap_agent(random_agent, player, self.env) for player in (0, 1)]
        expected = random.Random(42)
        self.assertEqual(agents[0](observation(), {}), [expected.randrange(2)])
        agents[1](observation(1), {})
        self.assertEqual(agents[0](observation(), {}), [expected.randrange(2)])
        self.assertEqual(state, random.getstate())

    def test_unique_folders_and_failed_setup(self):
        another = MatchLogger(self.temp.name, [pick, pick], ["A", "B"], 42, {})
        self.assertNotEqual(self.logger.path, another.path)
        summary = another.finalize(None, [], "missing simulator")
        self.assertEqual(summary["status"], "failed")
        self.assertTrue((another.path / "summary.txt").exists())

    def test_game_split_retains_incomplete_final_game(self):
        frames = [{"current": {"result": 2}}, {"current": {"result": -1}}]
        self.assertEqual(split_games(frames), [[frames[0]], [frames[1]]])


if __name__ == "__main__":
    unittest.main()
