"""Proprietà di round trip (§2 P1 passo 6, §4.4 punto 1) su frammenti sintetici generati.

Versione ridotta, per la suite: la prova completa (500 frammenti × 100 chiavi) è
``python -m multimark.cli.selftest`` e il suo esito è in ``docs/milestone_logs/P1_selftest.txt``.
"""

from __future__ import annotations

import random

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from multimark._astindex import AstIndex
from multimark.cli.selftest import PROFILES, add_comments, readings, strip_comments
from multimark.detect import detect
from multimark.embed import embed
from multimark.layout import build_layout
from multimark.synthetic import generate

SETTINGS = settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@SETTINGS
@given(
    seed=st.integers(0, 10**6),
    n_statements=st.integers(3, 45),
    n_functions=st.integers(1, 3),
    key=st.integers(0, 2**31 - 1),
    profile=st.sampled_from(sorted(PROFILES)),
)
def test_roundtrip(seed: int, n_statements: int, n_functions: int, key: int, profile: str) -> None:
    cfg = PROFILES[profile]
    method = "mcss" if profile == "mcss" else "multimark"
    code = generate(seed, n_statements, n_functions)
    msg = [random.Random(key).getrandbits(1) for _ in range(cfg.message_bits)]
    r = embed(code, msg, key, cfg)
    assert r.status in ("OK", "PARTIAL"), (r.reason, r.extra.get("error"))
    assert r.extra["skipped_sites"] == 0
    d = detect(r.code, msg, key, cfg, registry_sizes=(1,), method=method)
    n_votes = d.extra["n_votes"]
    assert d.extra["agreement"] == n_votes - r.extra["n_names_wrong"]
    expected = "".join(map(str, msg))
    if r.extra["n_names_wrong"] == 0:
        assert d.decoded_message in (None, expected)  # mai un messaggio sbagliato
    layout = build_layout(AstIndex.from_code(r.code), cfg, key)
    covered = len({i for s in layout.slots for i in s.indices}) == cfg.codeword_length
    if covered and r.extra["n_names_wrong"] == 0:
        assert d.decoded_message == expected
    if r.extra["n_sites"] < cfg.codeword_length:
        assert d.extra["n_erasures"] > 0 or d.extra["decode_status"] == "ok"


@SETTINGS
@given(seed=st.integers(0, 10**6), key=st.integers(0, 2**31 - 1),
       profile=st.sampled_from(sorted(PROFILES)))  # fmt: skip
def test_readings_invariant_to_comments(seed: int, key: int, profile: str) -> None:
    cfg = PROFILES[profile]
    code = generate(seed, 20, 2)
    msg = [random.Random(seed).getrandbits(1) for _ in range(cfg.message_bits)]
    marked = embed(code, msg, key, cfg).code
    base = readings(marked, cfg, key)
    assert readings(add_comments(marked), cfg, key) == base
    assert readings(strip_comments(add_comments(marked)), cfg, key) == base


def test_readings_invariant_to_black() -> None:
    black = __import__("pytest").importorskip("black")
    for seed in range(8):
        for cfg in PROFILES.values():
            code = generate(seed, 25, 2)
            msg = [random.Random(seed).getrandbits(1) for _ in range(cfg.message_bits)]
            marked = embed(code, msg, 1000 + seed, cfg).code
            reformatted = black.format_str(add_comments(marked), mode=black.Mode(line_length=60))
            assert readings(reformatted, cfg, 1000 + seed) == readings(marked, cfg, 1000 + seed)
