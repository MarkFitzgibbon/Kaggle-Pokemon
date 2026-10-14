import os

def load_deck():
    path = "/kaggle_simulations/agent/deck.csv"

    if not os.path.exists(path):
        path = "deck.csv"

    with open(path) as f:
        deck = [
            int(line.strip())
            for line in f
            if line.strip()
        ]

    assert len(deck) == 60
    return deck


def agent(obs: dict) -> list[int]:
    selection = obs["select"]

    # Initial deck-selection phase
    if selection is None:
        return load_deck()

    count = selection["maxCount"]

    # Choose the first option, or the first N options for multi-selection prompts.
    return list(range(count))
