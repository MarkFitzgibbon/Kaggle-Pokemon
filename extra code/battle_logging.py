"""Local match logging. This module is not needed by a submitted agent."""

import copy
import hashlib
import inspect
import io
import json
import platform
import random
import time
import traceback
import uuid
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path


SCHEMA_VERSION = 1
BAD_STATUSES = {"INVALID", "ERROR", "TIMEOUT"}
_diagnostics = ContextVar("decision_diagnostics", default=None)


def record_decision_details(**details):
    """An agent may report scores, reasoning, model version, etc. for this action."""
    target = _diagnostics.get()
    if target is not None:
        target.update(copy.deepcopy(details))


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "tolist"):
        return value.tolist()
    return {"python_type": type(value).__name__, "repr": repr(value)}


def encode(value, **kwargs):
    return json.dumps(value, ensure_ascii=False, default=_json_default, **kwargs)


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encode(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def append_jsonl(path, value):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(encode(value, separators=(",", ":")) + "\n")


def split_games(frames):
    """Native CABT frames end each game with current.result >= 0."""
    games, current = [], []
    for frame in frames:
        current.append(frame)
        if frame.get("current", {}).get("result", -1) >= 0:
            games.append(current)
            current = []
    if current:
        games.append(current)
    return games


def feature_observation(observation):
    # The opaque simulator search snapshot is retained in decisions.jsonl only.
    return {key: value for key, value in observation.items() if key != "search_begin_input"}


class MatchLogger:
    def __init__(self, logs_root, agents, labels, seed, configuration, tag=""):
        self.started = time.perf_counter()
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ") + "_" + uuid.uuid4().hex[:8]
        self.path = Path(logs_root) / self.run_id
        self.path.mkdir(parents=True, exist_ok=False)
        self.games = {}
        self.count = 0
        self.decks = {}
        self.errors = []
        self.metadata = {
            "schema_version": SCHEMA_VERSION, "match_id": self.run_id,
            "started_at": utc_now(), "status": "running", "tag": tag,
            "environment": "cabt", "configuration_requested": configuration,
            "python_version": platform.python_version(), "platform": platform.platform(),
            "seed": seed,
            "seed_scope": "Independent Python random streams per player; native CABT shuffles and model-library RNGs are not seeded.",
            "players": [],
        }
        for player, (agent, label) in enumerate(zip(agents, labels)):
            entry = {"player_id": player, "label": label, "python_random_seed": seed + player,
                     "callable": f"{agent.__module__}:{agent.__qualname__}"}
            source = inspect.getsourcefile(agent)
            if source and Path(source).is_file():
                data = Path(source).read_bytes()
                snapshot = f"agent_{player}.py"
                (self.path / snapshot).write_bytes(data)
                entry.update(source_file=str(Path(source).resolve()), source_snapshot=snapshot,
                             source_sha256=hashlib.sha256(data).hexdigest())
            self.metadata["players"].append(entry)
        write_json(self.path / "metadata.json", self.metadata)
        (self.path / "errors.log").touch()
        (self.path / "setup.jsonl").touch()

    def game_path(self, number):
        if number not in self.games:
            now, tick = utc_now(), time.perf_counter()
            for previous in self.games.values():
                if "ended_at" not in previous:
                    previous.update(ended_at=now, duration_seconds=tick - previous["started"])
            path = self.path / f"game_{number:03d}"
            path.mkdir()
            self.games[number] = {"path": path, "started_at": now, "started": tick}
            for filename in ("decisions.jsonl", "game.log", "errors.log"):
                (path / filename).touch()
        return self.games[number]["path"]

    def error(self, message, game=None):
        self.errors.append(message)
        for path in [self.path] + ([self.game_path(game)] if game else []):
            with (path / "errors.log").open("a", encoding="utf-8") as stream:
                stream.write(f"[{utc_now()}] {message}\n")

    def wrap_agent(self, agent, player, env):
        rng = random.Random(self.metadata["seed"] + player)
        signature = inspect.signature(agent)
        try:
            signature.bind({}, {})
            uses_configuration = True
        except TypeError:
            signature.bind({})
            uses_configuration = False

        def logged_agent(observation, configuration):
            snapshot = copy.deepcopy(observation)
            selection = snapshot.get("select")
            current = snapshot.get("current") or {}
            game = int(current.get("round", 1)) if selection is not None else None
            path = self.game_path(game) if game else self.path
            self.count += 1
            record = {
                "schema_version": SCHEMA_VERSION, "match_id": self.run_id,
                "decision_id": self.count, "game_number": game, "player_id": player,
                "agent_label": self.metadata["players"][player]["label"],
                "timestamp": utc_now(), "environment_step": len(env.steps) - 1,
                "turn": current.get("turn"), "phase": "deck_selection" if game is None else "game",
                "observation": snapshot, "available_options": (selection or {}).get("option", []),
                "action": None, "selected_options": None, "error": None,
            }
            # Persist input before calling the agent, even if the process later stops.
            append_jsonl(path / "inputs.jsonl", {key: record[key] for key in (
                "decision_id", "game_number", "player_id", "timestamp", "environment_step", "observation")})
            details = {}
            token = _diagnostics.set(details)
            out, err = io.StringIO(), io.StringIO()
            previous_random_state = random.getstate()
            random.setstate(rng.getstate())
            start = time.perf_counter()
            try:
                with redirect_stdout(out), redirect_stderr(err):
                    action = agent(observation, configuration) if uses_configuration else agent(observation)
                record["action"] = copy.deepcopy(action)
                if selection is None:
                    self.decks[str(player)] = copy.deepcopy(action)
                elif isinstance(action, list):
                    options = record["available_options"]
                    record["selected_options"] = [
                        {"index": index, "option": options[index] if isinstance(index, int) and 0 <= index < len(options) else None}
                        for index in action
                    ]
                return action
            except BaseException:
                record["error"] = traceback.format_exc()
                self.error(record["error"], game)
                raise
            finally:
                record["duration_ms"] = round((time.perf_counter() - start) * 1000, 6)
                rng.setstate(random.getstate())
                random.setstate(previous_random_state)
                _diagnostics.reset(token)
                record.update(stdout=out.getvalue(), stderr=err.getvalue(), diagnostics=details)
                append_jsonl(path / ("decisions.jsonl" if game else "setup.jsonl"), record)
                if game:
                    with (path / "game.log").open("a", encoding="utf-8") as stream:
                        stream.write(
                            f"Decision {record['decision_id']} | step {record['environment_step']} | "
                            f"turn {record['turn']} | player {player} ({record['agent_label']})\n"
                            f"Observation:\n{encode(feature_observation(snapshot), indent=2)}\n"
                            f"Available options:\n{encode(record['available_options'], indent=2)}\n"
                            f"Chosen action: {encode(record['action'])}\n"
                            f"Chosen options: {encode(record['selected_options'])}\n"
                            f"Decision time: {record['duration_ms']:.3f} ms\n"
                            f"Diagnostics: {encode(details)}\n"
                            f"stdout: {record['stdout']}\nstderr: {record['stderr']}\n"
                            f"Error: {record['error'] or 'none'}\n\n")
        return logged_agent

    def finalize(self, env, frames, failure=None):
        ended = utc_now()
        elapsed = time.perf_counter() - self.started
        for game in self.games.values():
            if "ended_at" not in game:
                game.update(ended_at=ended, duration_seconds=time.perf_counter() - game["started"])
        grouped = split_games(frames)
        for number in range(1, len(grouped) + 1):
            self.game_path(number)
        write_json(self.path / "decks.json", self.decks)
        state = env.steps[-1] if env is not None else []
        statuses = [player["status"] for player in state]
        rewards = [player["reward"] for player in state]
        invalid = any(status in BAD_STATUSES for status in statuses)
        match_complete = bool(env is not None and env.done and not failure and not invalid
                              and frames and frames[-1].get("current", {}).get("result", -1) >= 0)
        if invalid:
            self.error(f"Simulator final statuses: {statuses}; rewards: {rewards}", max(self.games, default=None))
        payload = env.toJSON() if env is not None else None
        if env is not None:
            payload["steps"][0][0]["visualize"] = frames
            write_json(self.path / "environment.json", payload)
            write_json(self.path / "simulator_logs.json", env.logs)
        summaries = []
        for number, game in sorted(self.games.items()):
            path = game["path"]
            game_frames = grouped[number - 1] if number <= len(grouped) else []
            result = game_frames[-1]["current"].get("result", -1) if game_frames else -1
            complete = result in (0, 1, 2)
            game_rewards = [1, -1] if result == 0 else [-1, 1] if result == 1 else [0, 0] if result == 2 else None
            records = [json.loads(line) for line in (path / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
            counts = Counter(record["player_id"] for record in records)
            times = {player: [record["duration_ms"] for record in records if record["player_id"] == player] for player in (0, 1)}
            summary = {
                "schema_version": SCHEMA_VERSION, "match_id": self.run_id, "game_number": number,
                "started_at": game["started_at"], "status": "completed" if complete else "incomplete",
                "ended_at": game.get("ended_at", ended),
                "duration_seconds": round(game.get("duration_seconds", 0), 6),
                "winner_player_id": result if result in (0, 1) else None,
                "draw": result == 2 if complete else None, "rewards": game_rewards,
                "turns": max((frame["current"].get("turn", 0) for frame in game_frames), default=0),
                "decisions": len(records), "decisions_by_player": dict(counts),
                "decision_time_ms": {str(player): {
                    "total": sum(values), "mean": sum(values) / len(values) if values else None,
                    "max": max(values) if values else None} for player, values in times.items()},
                "agent_errors": sum(record["error"] is not None for record in records),
                "players": self.metadata["players"], "decks": self.decks,
            }
            # Link each action to the next decision from the SAME player and game.
            following = {}
            transitions = []
            for record in reversed(records):
                player = record["player_id"]
                next_record = following.get(player)
                after_index = record["environment_step"] + 1
                after_state = env.steps[after_index][player] if env is not None and after_index < len(env.steps) else None
                action_applied = after_state is not None and after_state["status"] not in BAD_STATUSES and record["error"] is None
                transitions.append({
                    "schema_version": SCHEMA_VERSION, "match_id": self.run_id,
                    "game_number": number, "player_id": player, "decision_id": record["decision_id"],
                    "observation": feature_observation(record["observation"]), "action": record["action"],
                    "next_decision_id": next_record["decision_id"] if next_record else None,
                    "next_observation": feature_observation(next_record["observation"]) if next_record else None,
                    "terminal": complete and next_record is None,
                    "truncated": not complete and next_record is None,
                    "reward": game_rewards[player] if complete and next_record is None else 0 if next_record else None,
                    "game_reward": game_rewards[player] if complete else None,
                    "action_applied": action_applied,
                    "status_after_action": after_state["status"] if after_state else None,
                    "eligible_for_training": complete and action_applied,
                })
                following[player] = record
            with (path / "training.jsonl").open("w", encoding="utf-8") as stream:
                for transition in reversed(transitions):
                    stream.write(encode(transition) + "\n")
            with (path / "events.jsonl").open("w", encoding="utf-8") as stream:
                for index, frame in enumerate(game_frames):
                    stream.write(encode({"frame_index": index, "frame": frame}) + "\n")
            self._save_replay(env, payload, path, game_frames, records)
            write_json(path / "summary.json", summary)
            self._write_summary(path, summary)
            with (path / "game.log").open("a", encoding="utf-8") as stream:
                stream.write(f"Game ended: {summary['status']}; winner={summary['winner_player_id']}; "
                             f"draw={summary['draw']}; rewards={game_rewards}\n")
                if game_frames:
                    stream.write(f"Final simulator events:\n{encode(game_frames[-1].get('logs', []), indent=2)}\n")
            summaries.append(summary)
        self._save_replay(env, payload, self.path, frames)
        summary = {
            "schema_version": SCHEMA_VERSION, "match_id": self.run_id,
            "started_at": self.metadata["started_at"], "ended_at": ended,
            "duration_seconds": round(elapsed, 6),
            "status": "completed" if match_complete else "failed" if failure or invalid else "incomplete",
            "final_statuses": statuses, "final_rewards": rewards,
            "winner_player_id": rewards.index(1) if match_complete and 1 in rewards else None,
            "decisions": self.count, "games": summaries,
            "score": getattr(env, "result", None), "errors": self.errors,
        }
        self.metadata.update(status=summary["status"], ended_at=ended)
        if env is not None:
            self.metadata.update(configuration=dict(env.configuration), environment_version=env.specification.version)
        write_json(self.path / "metadata.json", self.metadata)
        write_json(self.path / "summary.json", summary)
        self._write_summary(self.path, summary)
        return summary

    def _save_replay(self, env, payload, path, frames, records=None):
        if env is None or not frames:
            (path / "replay_unavailable.txt").write_text("No simulator visual frames were available. See errors.log.\n", encoding="utf-8")
            return
        try:
            replay = payload
            if records is not None:
                replay = dict(payload)
                initial = [dict(player) for player in payload["steps"][0]]
                initial[0]["visualize"] = frames
                indices = sorted({record["environment_step"] + 1 for record in records})
                replay["steps"] = [initial] + [payload["steps"][index] for index in indices if index < len(payload["steps"])]
                result = frames[-1].get("current", {}).get("result", -1)
                if result in (0, 1, 2):
                    replay["rewards"] = [0, 0] if result == 2 else [1, -1] if result == 0 else [-1, 1]
                    replay["statuses"] = ["DONE", "DONE"]
            html = env.render(mode="html", environment=replay, logs=[], playing=True, controls=True)
            (path / "replay.html").write_text(html, encoding="utf-8")
        except Exception:
            self.error("Replay export failed:\n" + traceback.format_exc())
            (path / "replay_unavailable.txt").write_text("Replay export failed. See match errors.log.\n", encoding="utf-8")

    def _write_summary(self, path, summary):
        lines = [f"Match: {self.run_id}", f"Status: {summary['status']}"]
        if "game_number" in summary:
            winner = summary["winner_player_id"]
            result = f"player {winner} ({self.metadata['players'][winner]['label']})" if winner is not None else "draw" if summary["draw"] else "unknown"
            lines += [f"Game: {summary['game_number']}", f"Winner: {result}", f"Turns: {summary['turns']}",
                      f"Started: {summary['started_at']}", f"Ended: {summary['ended_at']}",
                      f"Duration: {summary['duration_seconds']:.3f} seconds",
                      f"Decisions: {summary['decisions']}", f"Rewards: {summary['rewards']}",
                      f"Decisions by player: {summary['decisions_by_player']}",
                      f"Decision times (ms): {encode(summary['decision_time_ms'])}"]
        else:
            lines += [f"Started: {summary['started_at']}", f"Ended: {summary['ended_at']}",
                      f"Duration: {summary['duration_seconds']:.3f} seconds",
                      f"Final rewards: {summary['final_rewards']}", f"Final statuses: {summary['final_statuses']}",
                      f"Score [player 0 wins, player 1 wins, draws]: {summary['score']}"]
            lines += [f"Game {game['game_number']}: {game['status']}; winner={game['winner_player_id']}; draw={game['draw']}" for game in summary["games"]]
        lines += [f"Player {player['player_id']}: {player['label']} ({player['callable']})" for player in self.metadata["players"]]
        (path / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
