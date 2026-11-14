"""I numeri di ``docs/reports/P1_esempi.md`` (tre esempi, chiave 20261711, messaggio «gpt4»,
matrice ``dmin4`` della base, §3.8 [v1.2.2]).

Se un test fallisce, l'inserimento o la rilevazione sono cambiati: il report va rigenerato e
riletto.
"""

from __future__ import annotations

from multimark.codec import text_to_bits
from multimark.config import multimark_base
from multimark.detect import detect
from multimark.embed import embed

KEY = 20261711
MSG = text_to_bits("gpt4")

# Codice identico a quello del report.
E1 = '''from typing import List, Optional


def longest(strings: List[str]) -> Optional[str]:
    """ Out of list of strings, return the longest one. Return the first one in case of multiple
    strings of the same length. Return None in case the input list is empty.
    >>> longest([])

    >>> longest(['a', 'b', 'c'])
    'a'
    >>> longest(['a', 'bb', 'ccc'])
    'ccc'
    """
    if not strings:
        return None

    maxlen = max(len(x) for x in strings)
    for s in strings:
        if len(s) == maxlen:
            return s
'''

E2 = """def moving_sums(values, width):
    out = []
    for i in range(0, len(values) - width + 1):
        window = values[i:i + width]
        out.append(sum(window))
    return out


def energy(samples):
    total = 0.0
    for sample in samples[0:len(samples)]:
        total += sample * sample  # potenza istantanea
    return total


def clip(x, lo, hi):
    if x is not None:
        if lo < hi:
            x = max(lo, min(x, hi))
    return x
"""

E3 = """def first_even(data, flag):
    if flag: evens = [v for v in data if v % 2 == 0]; return evens[:1]
    result = [w * 2 for w in data]
    if flag: picked = [u for u in result]
    return result
"""


def _run(code: str) -> tuple:
    cfg = multimark_base()
    r = embed(code, MSG, KEY, cfg)
    d = detect(r.code, MSG, KEY, cfg, registry_seed=20261001)
    return r, d


def test_example_1() -> None:
    r, d = _run(E1)
    assert (r.status, r.extra["n_sites"], r.extra["skipped_sites"], r.extra["n_renamed"]) == (
        "PARTIAL", 4, 0, 1,
    )  # fmt: skip
    assert "        return\n    else:\n" in r.code and "maxlen_count == len(s)" in r.code
    assert (d.extra["agreement"], d.extra["n_votes"]) == (4, 4)
    assert round(d.score, 2) == 1.20 and d.extra["n_erasures"] == 28


def test_example_2() -> None:
    r, d = _run(E2)
    assert (r.status, r.extra["n_sites"], r.extra["skipped_sites"], r.extra["n_renamed"]) == (
        "PARTIAL", 10, 0, 1,
    )  # fmt: skip
    for fragment in ("range(len(values) - width + 1)", "samples[:len(samples)]",
                     "sample ** 2  # potenza istantanea", "if x is not None and lo < hi:",
                     "result = []"):  # fmt: skip
        assert fragment in r.code
    assert (d.extra["agreement"], d.extra["n_votes"]) == (10, 10)
    assert round(d.score, 2) == 3.01


def test_example_3() -> None:
    r, d = _run(E3)
    assert (r.status, r.extra["n_sites"], r.extra["skipped_sites"]) == ("PARTIAL", 9, 1)
    assert "if flag: picked = [u for u in output]" in r.code and "return evens[0:1]" in r.code
    assert (d.extra["agreement"], d.extra["n_votes"]) == (8, 9)
    assert round(d.score, 2) == 1.71 and round(d.extra["score_nreg16"], 2) == 1.71
    assert round(d.extra["score_nreg1024"], 2) == 2.71
    assert d.extra["best_nreg1024"] != "".join(map(str, MSG))
