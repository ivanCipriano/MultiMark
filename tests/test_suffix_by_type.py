"""Opzione ``names.suffix_by_type`` (§3.11 [v1.3.9], MD30): i suffissi dei candidati si filtrano con
il tipo dedotto dal codice; tipo ignoto → solo suffissi neutri; prefisso ``the_`` escluso; se nessun
candidato filtrato ha i bit giusti si usa l'elenco completo (senza ``the_``), contato in
``n_names_type_fallback``. La lettura non cambia: il bit si legge dal nome."""

from __future__ import annotations

import random
import textwrap
from typing import Optional

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from multimark._astindex import AstIndex
from multimark.codec import encode
from multimark.config import Config, mcss_profile, multimark_base
from multimark.detect import detect
from multimark.embed import embed
from multimark.layout import build_layout
from multimark.names import (
    EXTRA_SUFFIXES,
    NEUTRAL_SUFFIXES,
    SUFFIXES,
    StaticProposer,
    allowed_suffixes,
    deduce_type,
    filter_by_type,
    name_bits,
    name_sites,
    normalize_name,
)
from multimark.synthetic import generate

ON = multimark_base().with_(names_suffix_by_type="on")
SETTINGS = settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
ALL_SUFFIXES = frozenset((*SUFFIXES, *EXTRA_SUFFIXES))


def _types(code: str) -> dict[str, Optional[str]]:
    index = AstIndex.from_code(textwrap.dedent(code).lstrip("\n"))
    sites = name_sites(index, include_params=True, module_level=True)
    return {s.name: deduce_type(index, s) for s in sites}


# ---------------------------------------------------------------------- tipo dedotto


def test_deduce_type() -> None:
    code = """
    def f(param, xs):
        int_lit = 3
        float_lit = 2.5
        str_lit = "a"
        bool_lit = True
        length = len(xs)
        typed_int = int(param)
        typed_float = float(param)
        text = input()
        stripped = text.strip()
        words = text.split()
        ordered = sorted(xs)
        made_list = [1, 2]
        comp_list = [v for v in xs]
        made_dict = {}
        made_set = {1}
        cond = param > 1
        negated = not cond
        unknown_call = foo(param)
        for idx_var in range(3):
            pass
        for elem_var in xs:
            pass
        return (int_lit, float_lit, str_lit, bool_lit, length, typed_int, typed_float, stripped,
                words, ordered, made_list, comp_list, made_dict, made_set, negated, unknown_call,
                idx_var, elem_var)
    """
    got = _types(code)
    assert got["param"] is None and got["unknown_call"] is None
    assert got["int_lit"] == got["length"] == got["typed_int"] == "int"
    assert got["float_lit"] == got["typed_float"] == "float"
    assert got["str_lit"] == got["text"] == got["stripped"] == "str"
    assert got["bool_lit"] == got["cond"] == got["negated"] == "bool"
    assert got["words"] == got["ordered"] == got["made_list"] == got["comp_list"] == "list"
    assert got["made_dict"] == "dict" and got["made_set"] == "set"
    assert got["idx_var"] == "index" and got["elem_var"] == "element"


def test_allowed_suffixes() -> None:
    assert allowed_suffixes("cost", None) == NEUTRAL_SUFFIXES
    assert "list" in allowed_suffixes("cost", "list") and "list" not in allowed_suffixes(
        "cost", "int"
    )
    assert "count" in allowed_suffixes("cost", "int") and "idx" not in allowed_suffixes(
        "cost", "int"
    )
    assert "idx" in allowed_suffixes("pos", "index")
    # una parola di tipo nel nome: solo neutri
    assert allowed_suffixes("count", "int") == NEUTRAL_SUFFIXES
    assert allowed_suffixes("itemList", "list") == NEUTRAL_SUFFIXES
    assert NEUTRAL_SUFFIXES <= allowed_suffixes("cost", "str")


def test_filter_keeps_order_and_drops_the_prefix() -> None:
    cands = ["price", "cost_value", "cost_list", "cost_count", "cur_cost", "the_cost", "cost_idx",
             "new_cost", "cost_tmp"]  # fmt: skip
    assert filter_by_type(cands, "cost", "int") == [
        "price", "cost_value", "cost_count", "cur_cost", "new_cost", "cost_tmp",
    ]  # fmt: skip
    assert filter_by_type(cands, "cost", None) == [
        "price", "cost_value", "cur_cost", "new_cost", "cost_tmp",
    ]  # fmt: skip


def test_incoherent_suffixes_never_proposed() -> None:
    proposer = StaticProposer()
    code = "def f(a):\n    cost = 0\n    count = 0\n    return cost, count, a\n"
    index = AstIndex.from_code(code)
    sites = {s.name: s for s in name_sites(index)}
    cost = filter_by_type(proposer.propose(code, "f", "cost", k=32), "cost", "int")
    assert "cost_list" not in cost and "the_cost" not in cost and "cost_count" in cost
    count = filter_by_type(proposer.propose(code, "f", "count", k=32), "count",
                           deduce_type(index, sites["count"]))  # fmt: skip
    assert "count_idx" not in count and "count_count" not in count and "count_val" in count


# ---------------------------------------------------------------------- inserimento


def _want(code: str, cfg: Config, key: int, msg: list[int]) -> tuple[str, int]:
    layout = build_layout(AstIndex.from_code(code), cfg, key)
    (slot,) = layout.names
    cw = encode(msg, cfg.t, cfg.code_matrix)
    want = 0
    for i in slot.indices:
        want = 2 * want + cw[i]
    return slot.name.name, want  # type: ignore[union-attr]


class _ListProposer:
    """Sempre lo stesso elenco di candidati."""

    def __init__(self, cands: list[str]) -> None:
        self.cands = cands

    def propose(self, code: str, function_name: str, var_name: str, k: int = 8) -> list[str]:
        return self.cands[:k]


CODE_COST = "def f(a):\n    cost = 0\n    return cost, a\n"


def _fallback_case(the_only: bool) -> tuple[int, list[int], list[str], str]:
    """Chiave e messaggio per cui ``cost`` ha il bit sbagliato; candidati ammessi tutti col bit
    sbagliato e un candidato con il bit giusto fuori dal filtro (``cost_list``, o ``the_cost``)."""
    for key in range(200):
        msg = [random.Random(key).getrandbits(1) for _ in range(ON.message_bits)]
        name, want = _want(CODE_COST, ON, key, msg)
        if name_bits(key, "cost", 1) == want:
            continue
        good = "the_cost" if the_only else "cost_list"
        if name_bits(key, good, 1) != want:
            continue
        allowed = [f"cost_{s}" for s in sorted(allowed_suffixes("cost", "int"))
                   if name_bits(key, f"cost_{s}", 1) != want]  # fmt: skip
        tail = ["cost_list"] if the_only and name_bits(key, "cost_list", 1) != want else []
        if the_only and not tail:
            continue
        return key, msg, [*allowed, good, *tail], good
    raise AssertionError("no key found")


def test_fallback_to_full_list_is_counted() -> None:
    key, msg, cands, good = _fallback_case(the_only=False)
    r = embed(CODE_COST, msg, key, ON, proposer=_ListProposer(cands))
    assert "cost_list = 0" in r.code
    assert r.extra["n_names_type_fallback"] == 1 and r.extra["n_names_no_candidate"] == 0
    d = detect(r.code, msg, key, ON, registry_sizes=(1,))
    assert d.extra["agreement"] == d.extra["n_votes"] - r.extra["n_names_wrong"]


def test_the_prefix_is_not_used_even_in_the_fallback() -> None:
    key, msg, cands, good = _fallback_case(the_only=True)
    r = embed(CODE_COST, msg, key, ON, proposer=_ListProposer(cands))
    assert "the_cost" not in r.code and "cost = 0" in r.code
    assert r.extra["n_names_type_fallback"] == 0 and r.extra["n_names_no_candidate"] == 1
    assert r.extra["n_names_wrong"] == 1
    # con l'opzione spenta lo stesso elenco dà the_cost
    off = embed(CODE_COST, msg, key, multimark_base(), proposer=_ListProposer(cands))
    assert "the_cost = 0" in off.code and "n_names_type_fallback" not in off.extra


def test_no_candidate_counts_wrong_votes_with_two_bits() -> None:
    cfg = ON.with_(names_bits_per_name=2)
    checked = 0
    for key in range(40):
        msg = [random.Random(key).getrandbits(1) for _ in range(cfg.message_bits)]
        name, want = _want(CODE_COST, cfg, key, msg)
        have = name_bits(key, "cost", 2)
        if have == want:
            continue
        cands = [
            f"cost_{s}" for s in sorted(ALL_SUFFIXES) if name_bits(key, f"cost_{s}", 2) != want
        ]
        r = embed(CODE_COST, msg, key, cfg, proposer=_ListProposer(cands))
        assert "cost = 0" in r.code and r.extra["n_names_no_candidate"] == 1
        assert r.extra["n_names_wrong"] == bin(have ^ want).count("1")
        checked += 1
    assert checked >= 10


def _renamed_pairs(code: str, marked: str, cfg: Config, key: int) -> list[tuple]:
    index0 = AstIndex.from_code(code)
    before = {s.uid: s for s in build_layout(index0, cfg, key).names}
    after = {s.uid: s for s in build_layout(AstIndex.from_code(marked), cfg, key).names}
    out = []
    for uid, s0 in before.items():
        assert s0.name is not None and after[uid].name is not None
        new = after[uid].name.name  # type: ignore[union-attr]
        if new != s0.name.name:
            out.append((s0.name.name, new, deduce_type(index0, s0.name)))
    return out


@SETTINGS
@given(
    seed=st.integers(0, 10**6),
    n_statements=st.integers(3, 40),
    n_functions=st.integers(1, 3),
    key=st.integers(0, 2**31 - 1),
    bits_per_name=st.sampled_from([1, 2]),
)
def test_marked_suffixes_agree_with_type(
    seed: int, n_statements: int, n_functions: int, key: int, bits_per_name: int
) -> None:
    code = generate(seed, n_statements, n_functions)
    cfg = ON.with_(names_bits_per_name=bits_per_name)
    msg = [random.Random(key).getrandbits(1) for _ in range(cfg.message_bits)]
    r = embed(code, msg, key, cfg)
    if r.status == "FAILED":
        assert r.reason == "no_sites", r.reason
        return
    assert r.extra["skipped_sites"] == 0
    d = detect(r.code, msg, key, cfg, registry_sizes=(1,))
    assert d.extra["agreement"] == d.extra["n_votes"] - r.extra["n_names_wrong"]
    incoherent = 0
    for old, new, typ in _renamed_pairs(code, r.code, cfg, key):
        assert not new.startswith("the_"), (old, new)
        base = normalize_name(old)
        suffix = new[len(base) + 1 :] if new.startswith(base + "_") else None
        if suffix in ALL_SUFFIXES and suffix not in allowed_suffixes(old, typ):
            incoherent += 1
    assert incoherent <= r.extra["n_names_type_fallback"]


@pytest.mark.parametrize("bits_per_name", [1, 2])
def test_roundtrip_fixed_code(bits_per_name: int) -> None:
    code = textwrap.dedent(
        """
        def solve(values, limit):
            total = 0
            found = []
            for item in values:
                if item < limit:
                    found.append(item)
                    total = total + item
            label = str(total)
            return found, label


        data = [3, 4, 5]
        result = solve(data, 4)
        """
    ).lstrip("\n")
    cfg = ON.with_(names_bits_per_name=bits_per_name)
    for key in range(10):
        msg = [random.Random(key).getrandbits(1) for _ in range(cfg.message_bits)]
        r = embed(code, msg, key, cfg)
        assert r.status in ("OK", "PARTIAL"), r.reason
        assert "the_" not in r.code
        d = detect(r.code, msg, key, cfg, registry_sizes=(1,))
        assert d.extra["agreement"] == d.extra["n_votes"] - r.extra["n_names_wrong"]
        assert r.extra["n_names_type_fallback"] >= 0


def test_off_has_no_fallback_field_and_same_output() -> None:
    code = generate(7, 25, 2)
    msg = [random.Random(3).getrandbits(1) for _ in range(24)]
    a = embed(code, msg, 3, multimark_base())
    b = embed(code, msg, 3, multimark_base().with_(names_suffix_by_type="off"))
    assert a.code == b.code and a.extra == b.extra
    assert "n_names_type_fallback" not in a.extra


def test_config_validation() -> None:
    with pytest.raises(ValueError):
        Config(names_suffix_by_type="yes")
    with pytest.raises(ValueError):
        mcss_profile().with_(names_suffix_by_type="on")
    assert ON.names_suffix_by_type == "on"
    assert multimark_base().names_suffix_by_type == mcss_profile().names_suffix_by_type == "off"


def test_selftest_options() -> None:
    from multimark.cli.selftest import profiles, run_case

    cfgs = profiles(2, "off", "const_left_zero", "on")
    assert cfgs["multimark"].canonical_natural_forms == "const_left_zero"
    assert cfgs["multimark"].names_suffix_by_type == "on"
    assert cfgs["mcss"] == mcss_profile()
    out = run_case(("multimark", 0, 0, 2, "off", "const_left", "on"))
    assert out["status"] in ("OK", "PARTIAL") and "type_fallback" in out
    assert run_case(("multimark", 0, 0)) == run_case(("multimark", 0, 0, 1, "off", "off", "off"))
