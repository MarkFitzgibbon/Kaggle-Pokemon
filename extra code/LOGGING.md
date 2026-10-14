# Local game logs

Run a best-of-three match from the project directory:

```powershell
py -3.11 testing/run_battle.py
```

The runner prints the new log folder immediately. It also works when launched
from `testing/` as `py -3.11 run_battle.py`. All default logs go to the project's
`logs/` directory, independent of the working directory. Older matches and the
existing top-level `replay.html` are preserved.

## Folder layout

Each match has a unique UTC timestamp and random suffix. Only games actually
started get a subfolder; a best-of-three match may finish after two games.

```text
logs/<timestamp>_<unique-id>/
    metadata.json          Agent identities, source hashes, versions, config, seeds
    agent_0.py             Snapshot of player 0's agent source module
    agent_1.py             Snapshot of player 1's agent source module
    decks.json             Exact submitted card ID lists, including duplicates
    inputs.jsonl           Inputs to the initial deck-selection calls
    setup.jsonl            Deck-selection decisions and any errors
    summary.txt            Readable match results and game scores
    summary.json           Match results and per-game statistics for comparisons
    console.log            Python startup/simulator stdout and stderr
    errors.log             Tracebacks, invalid statuses, and export errors
    environment.json       Full simulator match history
    simulator_logs.json    Simulator timing/output records
    replay.html            Visual replay of the entire match
    game_001/
        summary.txt        Readable result, turns, decisions, and timing
        summary.json       Structured game statistics, agent identities, and decks
        inputs.jsonl       Observations saved before each agent call
        decisions.jsonl    Full observations, options, choices, timing, diagnostics
        game.log           Readable detailed observations, options, and choices
        errors.log         Errors associated with this game
        training.jsonl     Same-player observation/action/next-observation records
        events.jsonl       Simulator visual frames, including terminal events
        replay.html        Visual replay for this game
    game_002/
        ...
```

JSONL is one JSON object per line and can be read a line at a time. Logs identify
players as **0** and **1**, matching the simulator. Game numbers start at **1**.
Decision IDs are unique within the match. Every completed decision stores the
original observation, complete available options, the returned action, resolved
selected options, elapsed milliseconds, stdout/stderr, and any exception.
Observations are copied before the agent runs so agent mutations cannot change
what the log says it originally saw. Source snapshots are the agent's defining
module; they do not bundle imported modules or model checkpoint files.

## Comparing agents

```powershell
py -3.11 testing/run_battle.py --agent0 main:agent --agent1 Agents.my_model:agent --label0 random --label1 model-v1 --seed 42 --tag experiment-01
```

Replace `Agents.my_model:agent` with an existing Python module and function.
Agents may accept `(observation)` or `(observation, configuration)` and must
return the usual list of indices (or the deck during initial selection).
`--bo 1` runs a single game. `--run-timeout 120` sets a match timeout in seconds.
The default remains best-of-three with a 2,000-second timeout. The runner can
also be imported without automatically starting a match:

```python
from main import agent
from testing.run_battle import run_match

folder = run_match([agent, agent], labels=["baseline A", "baseline B"], seed=42)
```

Use match `summary.json` files to compare results, game lengths, errors, and
decision times. Keep seat assignments in mind when comparing agents. The
metadata captures source hashes and the exact installed simulator version.

`--seed` gives each player an independent Python `random` stream (`seed` and
`seed + 1`). It does **not** seed CABT's native shuffle/coin-flip engine or
NumPy/PyTorch/model-owned generators. Set and record those model seeds separately
if used. A seed alone therefore does not reproduce a full match; the saved
replay preserves the match that actually happened. Run matches sequentially
within a process: CABT and the output capture use process-global state.

## Optional decision explanations

The logger records the actual observation and choice. It does not invent a
reason for the current random agent's choices. A future model can explicitly
attach JSON-compatible scores, diagnostics, checkpoint identifiers, or reasons:

```python
from battle_logging import record_decision_details

def agent(obs):
    # ... choose an action ...
    record_decision_details(
        reason="Highest estimated value",
        action_scores=[0.2, 0.8],
        checkpoint="model-v1",
    )
    return [1]
```

This hook records data only when called inside the local logging wrapper.
An agent that imports it must include this module when packaged elsewhere.
The existing `main.py` remains independent of the logger.

## Training data and failures

`training.jsonl` links an action to the **same player's next decision in the
same game**, potentially across several opponent actions. Its reward convention
is sparse: zero before the final decision and +1/-1/0 for a win/loss/draw on
that player's final decision. `game_reward` is the game outcome label on every
row. These are derived per-game training labels, not intermediate simulator
rewards. Match rewards are kept separately in the match summary.

Terminal rows have `terminal=true` and `next_observation=null`; the simulator
does not provide a fresh terminal observation to each agent. An incomplete
final row has `truncated=true`, a null reward, and is not marked terminal.
Filter on `eligible_for_training` to use only applied actions from completed
games. Deck selection is stored in `setup.jsonl`, outside gameplay training data.
`environment_step` indexes the pre-action state in the full match history;
`status_after_action` comes from the following state.

Training observations preserve what the agent received except the opaque
`search_begin_input` snapshot. Full raw observations remain in decision/input
logs. `events.jsonl`, replays, and the environment history contain simulator
views that may expose both hands and deck orders; use the training observations
as model inputs to avoid learning from information unavailable during play.

```python
import json
from pathlib import Path

for path in Path("logs").glob("*/game_*/training.jsonl"):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            sample = json.loads(line)
            if sample["eligible_for_training"]:
                observation, action = sample["observation"], sample["action"]
                # Feed these into your dataset builder.
```

Inputs and decisions are appended during play. Handled failures, timeouts, and
Ctrl+C preserve available data and produce partial summaries/replays before
propagating the error. If no visual frames are available, `replay_unavailable.txt`
explains why. A forced process kill can leave metadata marked `running` and no
final summaries; already-written JSONL rows remain available. Detailed logs and
full replays can use tens of megabytes per match. Logging is enabled by this
local runner; calling the standalone tournament agent does not write files.

Run the focused tests with:

```powershell
py -3.11 -m unittest discover -s testing -p 'test_*.py' -v
```
