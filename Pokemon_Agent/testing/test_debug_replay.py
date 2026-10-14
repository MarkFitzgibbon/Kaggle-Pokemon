import json
import tempfile
import unittest
from pathlib import Path

from debug_replay import add_debug_panel, build_debug_frames, describe_option


class DebugReplayTests(unittest.TestCase):
    def setUp(self):
        self.frame = {
            "current": {"yourIndex": 0, "turn": 2, "turnActionCount": 3, "result": -1,
                        "players": [{"hand": [{"name": "Ultra Ball"}, {"name": "Basic Energy"}],
                                     "active": [{"name": "Mewtwo"}], "bench": [{"name": "Zubat"}]}, {}]},
            "select": {"context": "Main", "minCount": 1, "maxCount": 1,
                       "option": [{"type": "Play", "index": 0},
                                  {"type": "Attach", "area": 2, "index": 1, "inPlayArea": 5, "inPlayIndex": 0}]},
        }

    def test_descriptions_resolve_cards_and_targets(self):
        self.assertEqual(describe_option(self.frame["select"]["option"][0], self.frame), "Play Ultra Ball")
        self.assertEqual(describe_option(self.frame["select"]["option"][1], self.frame), "Attach Basic Energy to Zubat")
        self.assertEqual(describe_option({"type": "Attack", "attackId": 560}, self.frame),
                         "Attack with Mewtwo (attack ID 560)")

    def test_frame_alignment_terminal_and_safe_embedding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "summary.json").write_text(json.dumps({"agents": ["A </script>", "B"]}))
            game = root / "game_01"
            game.mkdir()
            (game / "summary.json").write_text('{"game": 1}')
            terminal = {"current": {**self.frame["current"], "result": 0}}
            (game / "events.json").write_text(json.dumps([self.frame, terminal]))
            decision = {"agent_index": 0, "turn": 2, "turn_action_count": 3, "chosen_indices": [1]}
            (game / "decisions.jsonl").write_text(json.dumps(decision) + "\n")
            frames = build_debug_frames(root)
            self.assertEqual(frames[0]["chosen"], [1])
            self.assertEqual(frames[1]["options"], [])
            source = '<html><head><script>renderer:n3,ui:"inline"</script></head><body></body></html>'
            html = add_debug_panel(source, root)
            self.assertIn('window.renderPokemonDebug(props.step)', html)
            self.assertIn('A \\u003c/script>', html)
            self.assertIn('id="pokemon-debug-data"', html)
            with self.assertRaises(ValueError):
                add_debug_panel(html, root)
            with self.assertRaises(ValueError):
                add_debug_panel('<html><head></head></html>', root)


if __name__ == "__main__":
    unittest.main()
