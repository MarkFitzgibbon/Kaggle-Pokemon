import os
import random

def load_deck():
    path = "/kaggle_simulations/agent/deck.csv"

    if not os.path.exists(path):
        path = "lucario_deck.csv"

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

    options = selection["option"]
    count = selection["maxCount"]

    # Randomly choose the required indices
    return random.sample(
        range(len(options)),
        count
    )

