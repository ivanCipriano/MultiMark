"""Frammenti sintetici per i test di proprietà e l'autovalidazione (PIPELINE_metodo.md §2 P1
passo 6, §4.4 punto 1).

``generate(seed, n_statements)`` costruisce in modo deterministico un modulo con una o più
funzioni che contengono siti di tutti i canali (1–14) e variabili del canale dei nomi, scritti a
caso nelle due forme. I frammenti sono codice valido ma non pensato per essere eseguito (i test con
esecuzione usano frammenti scritti a mano, ``tests/test_channels_exec.py``).
"""

from __future__ import annotations

import random

WORDS = (
    "item", "count", "total", "value", "index", "result", "score", "name", "size", "level",
    "node", "price", "weight", "row", "col", "key", "page", "line", "word", "point",
)  # fmt: skip


def _fresh(rng: random.Random, used: set[str]) -> str:
    """Nome nuovo di due parole, in snake_case o camelCase, con forma normalizzata mai usata
    (due nomi come ``word_row`` e ``wordRow`` nella stessa funzione impedirebbero la rinomina di
    stile di V1)."""
    while True:
        a, b = rng.sample(WORDS, 2)
        name = f"{a}_{b}" if rng.random() < 0.6 else f"{a}{b.capitalize()}"
        norm = f"{a}_{b}"
        if norm not in used:
            used.add(norm)
            return name


def _statement(kind: int, rng: random.Random, used: set[str], ind: str) -> list[str]:
    """Righe di un'istruzione che contiene un sito del canale ``kind`` (1–14 o 0 = solo nome)."""
    v = _fresh(rng, used)
    f = rng.random() < 0.5  # forma
    if kind == 1:
        upd = f"{v} = {v} + 1" if f else f"{v} += 2"
        return [f"{ind}{v} = n", f"{ind}{upd}"]
    if kind == 2:
        return [f"{ind}{v} = n < 3" if f else f"{ind}{v} = 3 > n"]
    if kind == 3:
        return [f"{ind}{v} = n == 1" if f else f"{ind}{v} = 1 != n"]
    if kind == 4:
        x = _fresh(rng, used)
        if f:
            return [f"{ind}{v} = []", f"{ind}for {x} in data:", f"{ind}    {v}.append({x} * 2)"]
        return [f"{ind}{v} = [{x} * 2 for {x} in data]"]
    if kind == 5:
        if f:
            return [f"{ind}if n:", f"{ind}    {v} = n", f"{ind}else:", f"{ind}    {v} = 0"]
        return [f"{ind}{v} = n if flag else 0"]
    if kind == 6:
        return [f"{ind}{v} = n + 1" if f else f"{ind}{v} = 2 * n"]
    if kind == 7:
        return [f"{ind}{v} = " + rng.choice(["[]", "{}", "list()", "dict()"])]
    if kind == 8:
        return [f"{ind}{v} = n is None" if f else f"{ind}{v} = n != None"]
    if kind == 9:
        return [f"{ind}{v} = range(0, n)" if f else f"{ind}{v} = range(n)"]
    if kind == 10:
        return [f"{ind}{v} = data[0:n]" if f else f"{ind}{v} = data[:n]"]
    if kind == 12:
        if f:
            return [f"{ind}if n:", f"{ind}    if flag:", f"{ind}        {v} = 1"]
        return [f"{ind}if n and flag:", f"{ind}    {v} = 1"]
    if kind == 13:
        return [f"{ind}{v} = n * n" if f else f"{ind}{v} = n ** 2"]
    return [f"{ind}{v} = n"]  # 0: solo un sito dei nomi


def generate(seed: int, n_statements: int = 30, n_functions: int = 1) -> str:
    """Modulo con ``n_functions`` funzioni di circa ``n_statements`` istruzioni ciascuna; ogni
    funzione apre con un ``else_return`` in forma 1 o finisce con uno in forma 0, e chiude con un
    ``return_none``."""
    rng = random.Random(seed)
    used: set[str] = set()
    out: list[str] = []
    for fi in range(n_functions):
        out.append(f"def func_{fi}(n, data, flag):")
        body: list[str] = []
        er_form1 = rng.random() < 0.5
        if er_form1:
            body += ["    if flag is None:", "        return 0"]
        for _ in range(n_statements):
            body += _statement(rng.choice([0, *range(1, 11), 12, 13]), rng, used, "    ")
        last = "    return None" if rng.random() < 0.5 else "    return"
        if er_form1:
            body.append(last)
        else:
            body += ["    if n:", "        return 1", "    else:", "    " + last]
        out += body
        out.append("")
        out.append("")
    return "\n".join(out).rstrip() + "\n"
