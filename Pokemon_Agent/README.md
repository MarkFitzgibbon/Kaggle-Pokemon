# Pokemon battle logs

Run a best-of-three match from the project folder:

```powershell
py testing/run_battle.py
```

Each run creates a unique folder under `logs/`:

```text
logs/match_<UTC timestamp>_<unique id>/
  summary.txt          Match winner, score, and each game's winner
  summary.json         Structured match and game summaries
  decks.json           Each agent's initial deck submission
  replay.html          Replay of this match
  game_01/
    summary.txt        Game winner, turn count, decision counts
    summary.json       Structured game result and final state
    moves.txt          Every agent decision, available options, chosen options
    decisions.jsonl    One JSON record per decision, including its observation
    events.json        Simulator replay frames, effects, and terminal state
  game_02/
    ...
  game_03/             Created only if a third game is played
    ...
```

Logs are exported after the match finishes, including available steps if the
runner raises an exception. A best-of-three can end after two games. Draws and
unfinished games are identified explicitly. Agent indices and option indices
are zero-based. Only the active agent has a choice on a given decision; inactive
agents' stale observations are not logged as decisions. Setup choices, attacks,
card plays, and intermediate selections are all included.

`moves.txt` uses readable simulator selection types where available. The JSON
decision records preserve the exact options and observation the agent received,
its submitted indices, and the corresponding selected options. `events.json`
also includes automatic effects and the last move's consequences; these replay
frames can include hidden information and are intended for offline analysis.

To compare other agents, call the runner with distinct display names:

```python
from testing.run_battle import run_match
from main import agent

run_match(agents=(agent, agent), agent_names=("Random A", "Random B"))
```

Run the logger checks with `py -m unittest testing.test_battle_logging`.

The HTML replay includes a synchronized **Battle decisions** panel showing the
game, turn, active agent, and all available option indices with readable move
descriptions. The submitted options are highlighted. Expand **Raw option** for
the simulator fields. The other agent is shown as waiting because only one agent
chooses at a time. Turn 0 is setup. Attacks include the Pokémon and attack ID;
the simulator replay does not supply attack names. The panel works offline and
updates with the replay's playback, step buttons, and slider.

Run replay checks with `py -m unittest testing.test_debug_replay`.
