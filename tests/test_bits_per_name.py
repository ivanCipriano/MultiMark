"""Opzione ``names.bits_per_name`` (§3.11, §6.3 [v1.3.1]; MD27): con 2, una variabile V2 porta 2
bit (2 bit PRF del nome normalizzato su 2 posizioni della parola di codice); il candidato è valido
se entrambi coincidono; fino a 32 candidati come con 1 bit."""

from __future__ import annotations

import json
import random
from collections import Counter
from pathlib import Path

import pytest

from multimark._astindex import AstIndex
from multimark.codec import encode
from multimark.config import mcss_profile, multimark_base
from multimark.detect import detect
from multimark.embed import embed
from multimark.layout import build_layout, name_value
from multimark.linking import offset, phi_positional, phi_single_run
from multimark.names import MAX_CANDIDATES, name_bit, name_bits

CODE = """\
def f(data, flag):
    total_count = 0
    item_list = []
    for value in data:
        total_count = total_count + 1
        item_list.append(value)
    result = total_count if flag else 0
    return result, item_list


def g(rows):
    row_sum = 0
    best_row = None
    return row_sum, best_row
"""

CFG2 = multimark_base().with_(names_bits_per_name=2)


def test_name_bits() -> None:
    values: Counter[int] = Counter()
    for key in range(20):
        for name in ("total_count", "totalCount", "item_list", "x", "best_row"):
            one, two = name_bits(key, name, 1), name_bits(key, name, 2)
            assert one == name_bit(key, name) == two >> 1  # la prima posizione legge il bit V2
            values[two] += 1
        # i bit vengono dal nome normalizzato: tutte le rese di stile leggono lo stesso valore
        assert (
            len({name_bits(key, n, 2) for n in ("total_count", "totalCount", "TOTAL_COUNT")}) == 1
        )
    assert set(values) == {0, 1, 2, 3}
    with pytest.raises(ValueError):
        name_bits(1, "abc", 3)


def test_config_validation() -> None:
    assert multimark_base().names_bits_per_name == mcss_profile().names_bits_per_name == 1
    for variant in ("V0", "V1", "V1b", "V2b"):
        with pytest.raises(ValueError):
            multimark_base().with_(names_variant=variant, names_bits_per_name=2)
    with pytest.raises(ValueError):
        multimark_base().with_(names_bits_per_name=3)
    with pytest.raises(ValueError):
        mcss_profile().with_(names_bits_per_name=2)


def test_layout_function_channel() -> None:
    key = 77
    index = AstIndex.from_code(CODE)
    one = build_layout(index, multimark_base(), key)
    two = build_layout(index, CFG2, key)
    b = CFG2.codeword_length
    assert [s.key for s in two.slots] == [s.key for s in one.slots]
    assert two.n_bits == len(two.structural) + 2 * len(two.names)
    assert one.n_bits == len(one.structural) + len(one.names)
    for slot in two.names:
        assert slot.name is not None
        off = offset(key, slot.name.unit.name, slot.name.unit.n_params, "names", b)
        r = slot.name.rank
        assert slot.indices == ((off + 2 * r) % b, (off + 2 * r + 1) % b)
    assert [s.indices for s in two.structural] == [s.indices for s in one.structural]


def test_layout_other_linkings() -> None:
    key = 5
    index = AstIndex.from_code(CODE)
    b = CFG2.codeword_length
    run = build_layout(index, CFG2.with_(linking="function_single_run"), key)
    for slot in run.names:
        assert slot.name is not None
        unit = slot.name.unit
        i0, i1 = slot.indices
        r0 = next(r for r in range(64) if phi_single_run(key, unit.name, unit.n_params, r, b) == i0)
        assert phi_single_run(key, unit.name, unit.n_params, r0 + 1, b) == i1
    pos = build_layout(index, CFG2.with_(linking="positional"), key)
    phi = phi_positional(key, pos.n_bits, b)
    flat = [i for s in pos.slots for i in s.indices]
    assert flat == phi and all(len(s.indices) == 2 for s in pos.names)


def test_roundtrip_two_bits_per_name() -> None:
    for key in range(24):
        msg = [random.Random(key).getrandbits(1) for _ in range(24)]
        r = embed(CODE, msg, key, CFG2)
        assert r.status in ("OK", "PARTIAL") and r.extra["skipped_sites"] == 0
        layout = build_layout(AstIndex.from_code(r.code), CFG2, key)
        assert r.extra["n_sites"] == layout.n_bits
        cw = encode(msg, CFG2.t, CFG2.code_matrix)
        wrong = 0
        for slot in layout.names:
            value = name_value(slot, key, CFG2)
            assert value is not None
            wrong += int(value >> 1 != cw[slot.indices[0]]) + int(value & 1 != cw[slot.indices[1]])
        assert wrong == r.extra["n_names_wrong"]
        if r.extra["n_names_no_candidate"] == 0:
            assert wrong == 0
        d = detect(r.code, msg, key, CFG2, registry_sizes=(1,))
        assert d.extra["agreement"] == d.extra["n_votes"] - wrong
        assert d.extra["n_votes"] == layout.n_bits
        names_records = [s for s in d.extra["sites"] if s[2] in ("names", "names_b1")]
        assert len(names_records) == 2 * len(layout.names)


def test_original_name_kept_when_both_bits_match() -> None:
    hits = 0
    for key in range(40):
        msg = [random.Random(key).getrandbits(1) for _ in range(24)]
        cw = encode(msg, CFG2.t, CFG2.code_matrix)
        layout = build_layout(AstIndex.from_code(CODE), CFG2, key)
        keep = set()
        for slot in layout.names:
            assert slot.name is not None
            want = 2 * cw[slot.indices[0]] + cw[slot.indices[1]]
            if name_bits(key, slot.name.name, 2) == want:
                keep.add(slot.name.name)
        r = embed(CODE, msg, key, CFG2)
        out = build_layout(AstIndex.from_code(r.code), CFG2, key)
        assert {s.name.name for s in out.names if s.name} >= keep
        hits += len(keep)
    assert hits > 0


class _Proposer:
    """Candidati ``<nome>_c<j>``; registra i ``k`` chiesti."""

    def __init__(self) -> None:
        self.asked: list[int] = []

    def propose(self, code: str, function_name: str, var_name: str, k: int = 8) -> list[str]:
        self.asked.append(k)
        return [f"{var_name}_c{j}" for j in range(k)]


def test_up_to_32_candidates() -> None:
    code = "def f(a):\n    total_count = a\n    return total_count\n"
    found = {"late": False}
    for key in range(400):
        layout = build_layout(AstIndex.from_code(code), CFG2, key)
        (slot,) = layout.names
        msg = [random.Random(key).getrandbits(1) for _ in range(24)]
        cw = encode(msg, CFG2.t, CFG2.code_matrix)
        want = 2 * cw[slot.indices[0]] + cw[slot.indices[1]]
        cands = ["total_count"] + [f"total_count_c{j}" for j in range(MAX_CANDIDATES)]
        hits = [j for j, c in enumerate(cands) if name_bits(key, c, 2) == want]
        if hits and hits[0] > 8 and not found["late"]:
            proposer = _Proposer()
            r = embed(code, msg, key, CFG2, proposer=proposer)
            assert proposer.asked == [8, MAX_CANDIDATES]
            assert f"total_count_c{hits[0] - 1} = a" in r.code
            assert r.extra["n_names_no_candidate"] == 0 and r.extra["n_names_wrong"] == 0
            found["late"] = True
    assert found["late"]


class _NoMatchProposer(_Proposer):
    """Solo candidati con almeno un bit diverso da ``want``."""

    def __init__(self, key: int, want: int) -> None:
        super().__init__()
        self.key, self.want = key, want

    def propose(self, code: str, function_name: str, var_name: str, k: int = 8) -> list[str]:
        self.asked.append(k)
        out: list[str] = []
        j = 0
        while len(out) < k:
            cand = f"{var_name}_c{j}"
            if name_bits(self.key, cand, 2) != self.want:
                out.append(cand)
            j += 1
        return out


def test_no_candidate_keeps_the_name_and_counts_wrong_votes() -> None:
    code = "def f(a):\n    total_count = a\n    return total_count\n"
    checked = 0
    for key in range(30):
        (slot,) = build_layout(AstIndex.from_code(code), CFG2, key).names
        msg = [random.Random(key).getrandbits(1) for _ in range(24)]
        cw = encode(msg, CFG2.t, CFG2.code_matrix)
        want = 2 * cw[slot.indices[0]] + cw[slot.indices[1]]
        have = name_bits(key, "total_count", 2)
        if have == want:
            continue
        proposer = _NoMatchProposer(key, want)
        r = embed(code, msg, key, CFG2, proposer=proposer)
        assert proposer.asked == [8, MAX_CANDIDATES]
        assert r.extra["n_names_no_candidate"] == 1 and "total_count = a" in r.code
        assert r.extra["n_names_wrong"] == bin(have ^ want).count("1")  # 1 o 2 voti sbagliati
        checked += 1
    assert checked > 10


def test_inventory_bits_per_name(tmp_path: Path) -> None:
    from multimark.cli.inventory import main
    from multimark.inventory import inventory_code

    one = inventory_code(CODE)
    two = inventory_code(CODE, bits_per_name=2)
    assert two["n_sites_total"] == one["n_sites_total"] + one["n_vars"]
    assert two["n_sites_structural"] == one["n_sites_structural"]
    with pytest.raises(ValueError):
        inventory_code(CODE, bits_per_name=3)
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps({"code": CODE}) + "\n")
    js = tmp_path / "s.json"
    args = ["--input", str(inp), "--summary-json", str(js), "--summary", str(tmp_path / "s.txt")]
    assert main([*args, "--bits-per-name", "2"]) == 0
    summary = json.loads(js.read_text(encoding="utf-8"))
    assert summary["options"]["bits_per_name"] == 2
    assert "bits_per_name=2" in (tmp_path / "s.txt").read_text(encoding="utf-8")


def test_selftest_profiles_and_case() -> None:
    from multimark.cli.selftest import PROFILES, profiles, run_case

    cfgs = profiles(2, "binding_order")
    assert cfgs["mcss"] == PROFILES["mcss"] == mcss_profile()
    assert (cfgs["multimark"].names_bits_per_name, cfgs["multimark"].canonical_same_kind) == (
        2,
        "binding_order",
    )
    out = run_case(("multimark", 0, 0, 2, "binding_order"))
    assert out["status"] != "FAILED" and out["agreement_ok"] and not out["decoded_wrong"]
    assert run_case(("multimark", 0, 0)) == run_case(("multimark", 0, 0, 1, "off"))
