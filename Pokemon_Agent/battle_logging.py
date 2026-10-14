"""Export CABT matches without changing the agents or simulator."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def _write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _compact(value):
    return json.dumps(value, ensure_ascii=False)


def save_match_logs(env, agent_names, logs_dir="logs", error=None):
    """Save actual submitted actions alongside the observations that prompted them.

    Agent indices are zero-based, as in CABT. Only ACTIVE players make decisions;
    INACTIVE observations can be stale and must not be treated as new choices.
    Visualization frames provide readable names and game results. Their round
    field is not reliable, so terminal frames delimit games instead.
    """
    if len(agent_names) != 2 or len(set(agent_names)) != 2:
        raise ValueError("Provide two distinct agent names.")
    timestamp = datetime.now(timezone.utc)
    match_dir = Path(logs_dir) / (
        f"match_{timestamp:%Y%m%d_%H%M%S_%f}_{uuid4().hex[:8]}"
    )
    match_dir.mkdir(parents=True)
    steps = env.steps
    games = {}
    decks = []
    for step_index in range(len(steps) - 1):
        before, after = steps[step_index], steps[step_index + 1]
        for player_index, player in enumerate(before):
            if player["status"] != "ACTIVE":
                continue
            obs = player["observation"]
            action = after[player_index].get("action")
            if obs.get("select") is None:
                decks.append({"agent": agent_names[player_index], "agent_index": player_index,
                              "deck": action})
                continue
            current = obs["current"]
            game_number = current["round"]
            game = games.setdefault(game_number, {"decisions": [], "frames": []})
            selection = obs["select"]
            options = selection.get("option", [])
            chosen = [options[i] for i in action
                      if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(options)] if isinstance(action, list) else []
            game["decisions"].append({
                "decision": len(game["decisions"]) + 1,
                "environment_step": step_index,
                "turn": current.get("turn"),
                "turn_action_count": current.get("turnActionCount"),
                "agent": agent_names[player_index], "agent_index": player_index,
                "selection": selection, "available_options": options,
                "chosen_indices": action, "chosen_options": chosen,
                "status_after": after[player_index]["status"],
                "observation": {key: value for key, value in obs.items()
                                if key != "search_begin_input"},
            })

    frames = steps[0][0].get("visualize", []) if steps else []
    game_number = 1
    for frame in frames:
        game = games.setdefault(game_number, {"decisions": [], "frames": []})
        game["frames"].append(frame)
        result = frame.get("current", {}).get("result", -1)
        if result >= 0:
            game["result"] = result
            game["final_state"] = frame["current"]
            game_number += 1

    final = steps[-1] if steps else []
    statuses = [player["status"] for player in final]
    rewards = [player.get("reward") for player in final]
    summaries = []
    for number, game in sorted(games.items()):
        directory = match_dir / f"game_{number:02d}"
        directory.mkdir()
        decisions = game["decisions"]
        # Nonterminal visual frames correspond to successive decision prompts.
        prompts = [f for f in game["frames"] if f.get("current", {}).get("result", -1) < 0]
        if len(prompts) == len(decisions):
            for decision, frame in zip(decisions, prompts):
                current = frame["current"]
                readable = frame.get("select")
                if (current.get("yourIndex") == decision["agent_index"]
                        and current.get("turn") == decision["turn"]
                        and current.get("turnActionCount") == decision["turn_action_count"]
                        and readable is not None):
                    decision["readable_selection"] = readable
                    options = readable.get("option", [])
                    action = decision["chosen_indices"]
                    decision["readable_chosen_options"] = [options[i] for i in action
                        if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(options)] if isinstance(action, list) else []
        result = game.get("result")
        reason = "simulator result" if result is not None else "unfinished"
        # Invalid actions/timeouts end a game without a normal terminal frame.
        if result is None and number == max(games) and any(
                status in {"ERROR", "INVALID", "TIMEOUT"} for status in statuses):
            if rewards == [1, -1]:
                result = 0
            elif rewards == [-1, 1]:
                result = 1
            reason = "agent failure: " + ", ".join(statuses)
        winner = agent_names[result] if result in (0, 1) else None
        outcome = "win" if winner else "draw" if result == 2 else "unfinished"
        summary = {
            "game": number, "outcome": outcome, "winner": winner,
            "winner_index": result if result in (0, 1) else None,
            "result_code": result, "result_reason": reason,
            "turns": game.get("final_state", {}).get("turn",
                max((d["turn"] or 0 for d in decisions), default=0)),
            "decision_count": len(decisions),
            "decisions_by_agent": {name: sum(d["agent"] == name for d in decisions)
                                   for name in agent_names},
            "final_state": game.get("final_state"),
        }
        summaries.append(summary)
        _write_json(directory / "summary.json", summary)
        (directory / "summary.txt").write_text(
            f"Game {number}: {winner + ' won' if winner else outcome}\n"
            f"Result: {reason}\nTurns: {summary['turns']}\nDecisions: {len(decisions)}\n"
            + "\n".join(f"{name}: {count} decisions" for name, count in summary["decisions_by_agent"].items()) + "\n",
            encoding="utf-8")
        with (directory / "decisions.jsonl").open("w", encoding="utf-8") as output:
            for decision in decisions:
                output.write(_compact(decision) + "\n")
        with (directory / "moves.txt").open("w", encoding="utf-8") as output:
            for decision in decisions:
                selection = decision.get("readable_selection", decision["selection"])
                output.write(f"Decision {decision['decision']} | Turn {decision['turn']} | {decision['agent']}\n")
                output.write(f"Context: {selection.get('context')} | Type: {selection.get('type')}\n")
                output.write(f"Select between {selection.get('minCount')} and {selection.get('maxCount')} options\n")
                for index, option in enumerate(selection.get("option", [])):
                    output.write(f"  [{index}] {_compact(option)}\n")
                output.write(f"Chosen indices: {_compact(decision['chosen_indices'])}\n")
                output.write("Chosen options: " + _compact(decision.get("readable_chosen_options", decision["chosen_options"])) + "\n")
                output.write(f"Status after: {decision['status_after']}\n")
                output.write("Events before decision: " + _compact(decision["observation"].get("logs", [])) + "\n\n")
        # Includes automatic effects and the final move's consequences.
        _write_json(directory / "events.json", game["frames"])

    wins = {name: sum(s["winner"] == name for s in summaries) for name in agent_names}
    match_winner = agent_names[rewards.index(1)] if rewards in ([1, -1], [-1, 1]) else None
    summary = {
        "created_at": timestamp.isoformat(), "format": "best-of-3",
        "agents": list(agent_names), "winner": match_winner,
        "score": wins, "draws": sum(s["outcome"] == "draw" for s in summaries),
        "statuses": statuses, "rewards": rewards, "error": error,
        "environment_error": steps[0][0].get("error") if steps else None,
        "games": summaries,
    }
    _write_json(match_dir / "summary.json", summary)
    _write_json(match_dir / "decks.json", decks)
    (match_dir / "summary.txt").write_text(
        f"Best-of-3: {agent_names[0]} vs {agent_names[1]}\n"
        f"Match winner: {match_winner or ('draw' if rewards == [0, 0] and statuses == ['DONE', 'DONE'] else 'unfinished')}\n"
        f"Score: {wins[agent_names[0]]}-{wins[agent_names[1]]}\n"
        + "\n".join(f"Game {s['game']}: {s['winner'] or s['outcome']}" for s in summaries)
        + f"\nFinal statuses: {', '.join(statuses)}\n"
        + (f"Error: {error}\n" if error else ""), encoding="utf-8")
    return match_dir
