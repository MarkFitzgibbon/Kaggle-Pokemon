
"""Play a local CABT match and preserve its logs under logs/<match_id>/."""

import argparse
import importlib
import importlib.metadata
import secrets
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from battle_logging import MatchLogger, write_json


def load_agent(spec):
    module_name, separator, function_name = spec.partition(":")
    if not separator:
        raise ValueError("Use module:function for an agent, e.g. main:agent")
    agent = getattr(importlib.import_module(module_name), function_name)
    if not callable(agent):
        raise ValueError(f"{spec} is not callable")
    return agent


def replay_frames(env):
    frames = env.steps[0][0].get("visualize")
    if frames is not None:
        return frames
    # Recover completed games and the current partial game after an exception.
    from kaggle_environments.envs.cabt.cg.game import visualize_data
    from kaggle_environments.envs.cabt.cg.sim import Battle
    import json

    frames = list(Battle.vis)
    if not env.done and Battle.battle_ptr:
        frames.extend(json.loads(visualize_data()))
    return frames


def run_match(agents, labels=None, *, bo=3, seed=None, logs_root=None, tag="", run_timeout=2000):
    if len(agents) != 2 or (labels is not None and len(labels) != 2):
        raise ValueError("A match requires exactly two agents and two labels.")
    if bo < 1 or run_timeout <= 0:
        raise ValueError("bo and run_timeout must be positive.")
    seed = secrets.randbits(32) if seed is None else seed
    labels = labels or [f"{agent.__module__}:{agent.__qualname__} [player {i}]" for i, agent in enumerate(agents)]
    configuration = {"bo": bo, "runTimeout": run_timeout}
    logger = MatchLogger(logs_root or PROJECT_ROOT / "logs", agents, labels, seed, configuration, tag)
    print(f"Match logs: {logger.path}", flush=True)
    env, failure = None, None
    try:
        with (logger.path / "console.log").open("w", encoding="utf-8") as console:
            with redirect_stdout(console), redirect_stderr(console):
                from kaggle_environments import make
                logger.metadata["kaggle_environments_version"] = importlib.metadata.version("kaggle-environments")
                write_json(logger.path / "metadata.json", logger.metadata)
                env = make("cabt", configuration=configuration, info={"TeamNames": labels}, debug=True)
                env.run([logger.wrap_agent(agent, player, env) for player, agent in enumerate(agents)])
    except BaseException:
        failure = traceback.format_exc()
        logger.error(failure, max(logger.games, default=None))
        raise
    finally:
        frames = []
        if env is not None:
            try:
                frames = replay_frames(env)
            except Exception:
                logger.error("Unable to recover replay frames:\n" + traceback.format_exc())
        try:
            logger.finalize(env, frames, failure)
        finally:
            if env is not None and not env.done:
                from kaggle_environments.envs.cabt.cg.game import battle_finish
                from kaggle_environments.envs.cabt.cg.sim import Battle
                if Battle.battle_ptr:
                    battle_finish()
                    Battle.battle_ptr = None
    print(f"Final rewards: {[player.reward for player in env.steps[-1]]}")
    print(f"Final statuses: {[player.status for player in env.steps[-1]]}")
    print(f"Logs and replay saved: {logger.path}")
    return logger.path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent0", default="main:agent", help="Player 0 module:function")
    parser.add_argument("--agent1", default="main:agent", help="Player 1 module:function")
    parser.add_argument("--label0", default=None)
    parser.add_argument("--label1", default=None)
    parser.add_argument("--bo", type=int, default=3, help="Best-of format (default: 3)")
    parser.add_argument("--seed", type=int, default=None, help="Seed for Python random in agents")
    parser.add_argument("--tag", default="", help="Experiment/model checkpoint label")
    parser.add_argument("--run-timeout", type=float, default=2000)
    args = parser.parse_args()
    agents = [load_agent(args.agent0), load_agent(args.agent1)]
    labels = [args.label0 or args.agent0 + " [player 0]", args.label1 or args.agent1 + " [player 1]"]
    run_match(agents, labels, bo=args.bo, seed=args.seed, tag=args.tag, run_timeout=args.run_timeout)


if __name__ == "__main__":
    main()
