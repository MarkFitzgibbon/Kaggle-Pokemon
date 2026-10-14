import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from battle_logging import save_match_logs


def player(status, game=1, action=None, reward=0, selection=True):
    return {
        "status": status, "action": action, "reward": reward,
        "observation": {
            "select": {"minCount": 1, "maxCount": 1, "option": [{"type": 0}, {"type": 1}]} if selection else None,
            "current": {"round": game, "turn": 1, "turnActionCount": 1},
            "logs": [],
        },
    }


class MatchLoggingTests(unittest.TestCase):
    def test_two_game_sweep_pairs_choices_with_previous_observation(self):
        steps = [
            [player("ACTIVE", selection=False), player("ACTIVE", selection=False)],
            [player("ACTIVE", action=[42] * 60), player("INACTIVE", action=[43] * 60)],
            [player("INACTIVE", game=2, action=[1]), player("ACTIVE", game=2)],
            [player("DONE", game=2, reward=1), player("DONE", game=2, action=[0], reward=-1)],
        ]
        # CABT's replay incorrectly uses round 1 for every game.
        steps[0][0]["visualize"] = [
            {"current": {"round": 1, "result": 0, "turn": 1}},
            {"current": {"round": 1, "result": 0, "turn": 1}},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = save_match_logs(SimpleNamespace(steps=steps), ["A", "B"], temporary)
            summary = json.loads((path / "summary.json").read_text())
            self.assertEqual(summary["score"], {"A": 2, "B": 0})
            self.assertFalse((path / "game_03").exists())
            first = json.loads((path / "game_01/decisions.jsonl").read_text())
            second = json.loads((path / "game_02/decisions.jsonl").read_text())
            self.assertEqual((first["agent"], first["chosen_indices"]), ("A", [1]))
            self.assertEqual((second["agent"], second["chosen_indices"]), ("B", [0]))
            self.assertEqual(first["chosen_options"], [{"type": 1}])
            other = save_match_logs(SimpleNamespace(steps=steps), ["A", "B"], temporary)
            self.assertNotEqual(path, other)

    def test_draw_and_agent_failure(self):
        for terminal, statuses, rewards, expected in [
            (2, ["DONE", "DONE"], [0, 0], "draw"),
            (None, ["INVALID", "DONE"], [-1, 1], "win"),
            (None, ["ACTIVE", "INACTIVE"], [0, 0], "unfinished"),
        ]:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temporary:
                steps = [[player("ACTIVE"), player("INACTIVE")],
                         [player(statuses[0], action=[99], reward=rewards[0]),
                          player(statuses[1], reward=rewards[1])]]
                if terminal is not None:
                    steps[0][0]["visualize"] = [{"current": {"result": terminal, "turn": 1}}]
                path = save_match_logs(SimpleNamespace(steps=steps), ["A", "B"], temporary)
                summary = json.loads((path / "game_01/summary.json").read_text())
                self.assertEqual(summary["outcome"], expected)
                decision = json.loads((path / "game_01/decisions.jsonl").read_text())
                self.assertEqual(decision["chosen_indices"], [99])
                self.assertEqual(decision["chosen_options"], [])


if __name__ == "__main__":
    unittest.main()
