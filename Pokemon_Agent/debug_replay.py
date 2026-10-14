"""Add offline, frame-synchronized decision information to CABT HTML replays."""

import json
import re
from pathlib import Path


def describe_option(option, frame):
    current = frame.get("current", {})
    actor = current.get("yourIndex", 0)
    players = current.get("players", [])

    def card(area, index, player=actor):
        zones = {2: "hand", 4: "active", 5: "bench"}
        zone = zones.get(area)
        cards = players[player].get(zone, []) if zone and 0 <= player < len(players) else []
        if isinstance(cards, list) and isinstance(index, int) and 0 <= index < len(cards):
            return cards[index].get("name", f"Card {cards[index].get('id')}")
        return f"card {index} in {zone or ('area ' + str(area))}"

    kind = option.get("type", "Unknown")
    source = card(option.get("area", 2), option.get("index", 0), option.get("playerIndex", actor))
    target = card(option.get("inPlayArea"), option.get("inPlayIndex", 0))
    if kind == "Play":
        return "Play " + source
    if kind == "Attach":
        return f"Attach {source} to {target}"
    if kind == "Evolve":
        return f"Evolve {target} into {source}"
    if kind == "Card":
        return "Select " + source
    if kind == "Attack":
        return f"Attack with {card(4, 0)} (attack ID {option.get('attackId')})"
    if kind == "Ability":
        return "Use the ability of " + source
    if kind == "EnergyCard":
        zone = {4: "active", 5: "bench"}.get(option.get("area"))
        cards = players[option.get("playerIndex", actor)].get(zone, []) if zone else []
        index = option.get("index", 0)
        energies = cards[index].get("energyCards", []) if 0 <= index < len(cards) else []
        energy_index = option.get("energyIndex", 0)
        energy = energies[energy_index].get("name") if 0 <= energy_index < len(energies) else None
        return f"Select {energy or 'energy card ' + str(energy_index)} attached to {source}"
    if kind == "Energy":
        return f"Select {option.get('count', 1)} energy at index {option.get('energyIndex', 0)} on {source}"
    if kind == "Number":
        return f"Choose {option.get('number')}"
    if kind == "Yes":
        return "Yes — go first" if (frame.get("select") or {}).get("context") == "IsFirst" else "Yes"
    if kind == "No":
        return "No — go second" if (frame.get("select") or {}).get("context") == "IsFirst" else "No"
    if kind == "End":
        return "End the turn"
    if kind == "Retreat":
        return "Retreat the active Pokémon"
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(kind)) + " — " + json.dumps(option, ensure_ascii=False)


def build_debug_frames(match_dir):
    match_dir = Path(match_dir)
    summary = json.loads((match_dir / "summary.json").read_text(encoding="utf-8"))
    names = summary["agents"]
    output = []
    for directory in sorted(match_dir.glob("game_*")):
        game = json.loads((directory / "summary.json").read_text(encoding="utf-8"))["game"]
        frames = json.loads((directory / "events.json").read_text(encoding="utf-8"))
        decisions = [json.loads(line) for line in (directory / "decisions.jsonl").read_text(encoding="utf-8").splitlines()]
        position = 0
        for frame in frames:
            current = frame["current"]
            result = current.get("result", -1)
            decision = decisions[position] if result < 0 and position < len(decisions) else None
            if result < 0:
                position += 1
            # Do not highlight a submitted action against a mismatched prompt.
            if decision and any(current.get(key) != decision.get(other) for key, other in [
                    ("yourIndex", "agent_index"), ("turn", "turn"), ("turnActionCount", "turn_action_count")]):
                decision = None
            selection = frame.get("select") or {}
            actor = current.get("yourIndex", 0)
            output.append({
                "game": game, "turn": current.get("turn", 0),
                "agent": names[actor], "inactive_agent": names[1 - actor],
                "context": re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(selection.get("context", ""))),
                "minimum": selection.get("minCount"), "maximum": selection.get("maxCount"),
                "chosen": decision["chosen_indices"] if decision else None,
                "options": [{"index": index, "description": describe_option(option, frame), "raw": option}
                            for index, option in enumerate(selection.get("option", []))] if result < 0 else [],
                "result": (names[result] + " won") if result in (0, 1) else "Draw" if result == 2 else None,
            })
    return output


def add_debug_panel(replay_html, match_dir):
    """Hook the renderer's actual frame index, including playback and scrubbing."""
    if 'id="pokemon-debug-data"' in replay_html:
        raise ValueError("This replay already contains the debug panel.")
    pattern = r'renderer:([A-Za-z_$][\w$]*),ui:"inline"'
    replay_html, count = re.subn(pattern,
        lambda match: 'renderer:(props)=>{window.renderPokemonDebug(props.step);return '
        + match.group(1) + '(props)},ui:"inline"', replay_html, count=1)
    if count != 1:
        raise ValueError("CABT replay renderer changed; cannot synchronize the debug panel.")
    data = json.dumps(build_debug_frames(match_dir), ensure_ascii=False).replace("<", "\\u003c")
    assets = Path(__file__).parent / "replay_debug"
    css = (assets / "panel.css").read_text(encoding="utf-8")
    script = (assets / "panel.js").read_text(encoding="utf-8")
    injection = f'<style>{css}</style><script id="pokemon-debug-data" type="application/json">{data}</script><script>{script}</script>'
    return replay_html.replace("</head>", injection + "</head>", 1)
