"""Inserimento (§3.9) e rilevazione (§3.10): stati, round trip, opzioni di §3.11, registro."""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

import pytest

from multimark.codec import encode
from multimark.config import Config, mcss_profile, multimark_base
from multimark.detect import (
    EXTRA_FIELDS,
    binom_tail_score,
    detect,
    normal_tail_score,
    registry_decoys,
)
from multimark.embed import embed, message_to_bits
from multimark.prf import derive_seed
from tests.helpers import src

RICH = src(
    '''
    def summarize(records, key=None):
        """Riassume i record."""
        if len(records) == 0:
            return None
        names = [r for r in records]
        result = []
        for i in range(len(names)):
            name = names[i].strip()  # commento in riga
            if name == "" or name == "-":
                continue
            if key is not None:
                if key in name:
                    result.append(name[0:10])
            else:
                result.append(name.lower())
        total = 0
        for i, row in enumerate(records):
            total += row.get("value", None) or 0
        label = "Total: " + str(total)
        if total > 100:
            label = label + "!"
        return sorted(result)[::-1], label


    def scale(values, factor):
        out = []
        for v in values:
            out.append(v * 2)
        count = len(out)
        count = count + 1
        best = None
        if best is None:
            best = {}
        return [x * x for x in out], count, best, range(0, count), out[0:count]
    '''
)


def _msg(seed: int) -> list[int]:
    rng = random.Random(seed)
    return [rng.getrandbits(1) for _ in range(24)]


def test_syntax_error() -> None:
    r = embed("def f(:\n", _msg(0), 1, multimark_base())
    assert (r.status, r.reason, r.code) == ("FAILED", "syntax_error", "def f(:\n")
    d = detect("def f(:\n", _msg(0), 1, multimark_base())
    assert (d.status, d.reason) == ("FAILED", "syntax_error")


def test_no_sites() -> None:
    r = embed("print(1)\n", _msg(0), 1, multimark_base())
    assert (r.status, r.reason) == ("FAILED", "no_sites")
    d = detect("print(1)\n", _msg(0), 1, multimark_base(), registry_seed=1)
    assert (d.status, d.reason) == ("FAILED", "no_sites")


def test_message_formats() -> None:
    assert message_to_bits("0101", 4) == [0, 1, 0, 1]
    with pytest.raises(ValueError):
        message_to_bits("012", 3)
    with pytest.raises(ValueError):
        message_to_bits([0, 1], 3)
    with pytest.raises(ValueError):
        embed("x = 1\n", "01", 1, multimark_base())


@pytest.mark.parametrize(
    "cfg,method",
    [(multimark_base(), "multimark"), (mcss_profile(), "mcss")],
    ids=["multimark", "mcss"],
)
def test_roundtrip_all_votes_agree(cfg: Config, method: str) -> None:
    for seed in range(5):
        m = _msg(seed)
        r = embed(RICH, m, 1000 + seed, cfg)
        assert r.status in ("OK", "PARTIAL"), r.reason
        assert r.extra["skipped_sites"] == 0
        d = detect(r.code, "".join(map(str, m)), 1000 + seed, cfg, registry_seed=3, method=method)
        assert d.status == "OK"
        wrong = r.extra["n_names_wrong"]
        assert d.extra["agreement"] == d.extra["n_votes"] - wrong
        if wrong == 0:
            assert d.score == pytest.approx(d.extra["n_votes"] * math.log10(2))
        assert set(EXTRA_FIELDS) <= set(d.extra)


def test_comments_and_docstrings_survive() -> None:
    r = embed(RICH, _msg(1), 77, multimark_base())
    assert "# commento in riga" in r.code and '"""Riassume i record."""' in r.code


def test_status_ok_when_enough_sites() -> None:
    body = "".join(f"    v{i} = a[0:{i}]\n" for i in range(1, 40))
    code = "def f(a):\n" + body
    r = embed(code, _msg(2), 5, multimark_base())
    assert r.extra["n_sites"] >= 32 and r.status == "OK"
    d = detect(r.code, _msg(2), 5, multimark_base(), registry_seed=1)
    assert d.extra["decode_status"] == "ok"
    assert d.decoded_message == "".join(map(str, _msg(2)))
    assert d.extra["bits_correct"] == 24 and d.extra["score_decode"] == 1.0
    assert d.extra["best_nreg16"] == d.decoded_message
    assert d.native_decision is True


def test_wrong_key_scores_low() -> None:
    body = "".join(f"    v{i} = a[0:{i}]\n" for i in range(1, 40))
    code = "def f(a):\n" + body
    r = embed(code, _msg(3), 5, multimark_base())
    good = detect(r.code, _msg(3), 5, multimark_base(), registry_seed=1).score
    bad = detect(r.code, _msg(3), 6, multimark_base(), registry_seed=1).score
    assert good is not None and bad is not None and good > 10 > bad


@pytest.mark.parametrize(
    "changes",
    [{"linking": "function_single_run"}, {"linking": "positional"}, {"mask": "off"},
     {"canonical": "paper"}, {"names_variant": "V0"}, {"names_variant": "V1"},
     {"names_variant": "V1b"}, {"names_variant": "V2b"}, {"t": 0}, {"t": 4},
     {"channels": "mcss8"}, {"names_module_level": True}, {"names_include_params": True}],
)  # fmt: skip
def test_options_roundtrip(changes: dict) -> None:
    cfg = multimark_base().with_(**changes)
    m = _msg(4)
    r = embed(RICH, m, 4242, cfg)
    assert r.status in ("OK", "PARTIAL"), (r.reason, r.extra.get("error"))
    d = detect(r.code, m, 4242, cfg, registry_seed=9)
    wrong = r.extra["n_names_wrong"]
    assert d.extra["agreement"] == d.extra["n_votes"] - wrong


def test_embed_is_deterministic() -> None:
    a = embed(RICH, _msg(5), 11, multimark_base())
    b = embed(RICH, _msg(5), 11, multimark_base())
    assert a.code == b.code and a.extra == b.extra


def test_binomial_score() -> None:
    assert binom_tail_score(10, 10) == pytest.approx(10 * math.log10(2))
    assert binom_tail_score(10, 0) == 0.0
    expected = -math.log10(sum(math.comb(10, k) for k in range(7, 11)) / 1024)
    assert binom_tail_score(10, 7) == pytest.approx(expected)
    assert normal_tail_score(5, 10) == pytest.approx(-math.log10(0.5))


def test_registry_decoys() -> None:
    exp = _msg(6)
    decoys = registry_decoys(20261001, "multimark", 15, exp, 24)
    assert len(decoys) == 15 and all(len(d) == 24 for d in decoys)
    v1 = derive_seed(20261001, "multimark-registry", "1") % 2**24
    assert decoys[0] == [int(c) for c in format(v1, "024b")]
    assert registry_decoys(20261001, "multimark", 15, exp, 24) == decoys
    # un'esca uguale al messaggio atteso si sostituisce con quella di j + 10**6
    replaced = registry_decoys(20261001, "multimark", 1, decoys[0], 24)[0]
    v = derive_seed(20261001, "multimark-registry", str(1 + 10**6)) % 2**24
    assert replaced == [int(c) for c in format(v, "024b")]


def test_registry_seed_required_for_secondary_scores() -> None:
    r = embed(RICH, _msg(7), 1, multimark_base())
    with pytest.raises(ValueError):
        detect(r.code, _msg(7), 1, multimark_base())
    d = detect(r.code, _msg(7), 1, multimark_base(), registry_sizes=(1,))
    assert d.extra["score_nreg16"] is None and d.status == "OK"


def test_weighted_voting(tmp_path: Path) -> None:
    weights = tmp_path / "w.json"
    weights.write_text(json.dumps({"names": 0.5}), encoding="utf-8")
    cfg = multimark_base().with_(voting="weighted", channel_weights=str(weights))
    r = embed(RICH, _msg(8), 3, cfg)
    d = detect(r.code, _msg(8), 3, cfg, registry_seed=1)
    assert d.status == "OK" and d.native_decision is None
    erasure = multimark_base().with_(voting="weighted_erasure", channel_weights=str(weights))
    with pytest.raises(NotImplementedError):
        detect(r.code, _msg(8), 3, erasure, registry_seed=1)


def test_mcss_native_decision_uses_decoding() -> None:
    body = "".join(f"    v{i} = a[{i}] < 1\n" for i in range(1, 40))
    code = "def f(a):\n" + body
    r = embed(code, _msg(9), 5, mcss_profile())
    d = detect(r.code, _msg(9), 5, mcss_profile(), registry_seed=1, method="mcss")
    assert d.native_decision is (d.decoded_message == "".join(map(str, _msg(9))))


def test_detect_votes_match_codeword_positions() -> None:
    m = _msg(10)
    cfg = multimark_base()
    r = embed(RICH, m, 99, cfg)
    d = detect(r.code, m, 99, cfg, registry_seed=1)
    cw = encode(m, cfg.t, cfg.code_matrix)
    assert len(cw) == 32
    records = d.extra["sites"]
    assert all(len(rec) == 6 for rec in records)
    assert sum(1 for rec in records if rec[5] is not None) == d.extra["n_votes"]
