from pathlib import Path
import sys

# Support both `py testing/run_battle.py` and `py -m testing.run_battle`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from kaggle_environments import make
from main import agent
from determined import agent as determined
from battle_logging import save_match_logs
from debug_replay import add_debug_panel

def run_match(agents=(determined, agent), agent_names=("Determined", "Random")):
    if len(agents) != 2 or len(agent_names) != 2 or len(set(agent_names)) != 2:
        raise ValueError("Provide two agents and two distinct names.")
    env = make("cabt", configuration={"bo": 3}, debug=True)
    error = None
    try:
        steps = env.run(list(agents))
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        match_dir = save_match_logs(env, agent_names, PROJECT_ROOT / "logs", error)
        print(f"Battle logs saved to: {match_dir}")

    print("Final rewards:", [player.reward for player in steps[-1]])
    print("Final statuses:", [player.status for player in steps[-1]])
    replay = add_debug_panel(env.render(mode="html"), match_dir)
    (match_dir / "replay.html").write_text(replay, encoding="utf-8")
    (PROJECT_ROOT / "replay.html").write_text(replay, encoding="utf-8")
    print("Replay saved.")
    return env, match_dir


if __name__ == "__main__":
    run_match()
