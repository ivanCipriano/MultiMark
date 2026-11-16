"""Variabili di una lettera (``names.single_letter``, §3.11 e §4.2 punto 9 [v1.2.6]).

- ``exclude``: regola (c) di §3.6.1, ``len ≥ 2`` (default di entrambi i profili);
- ``extend_except_loop``: nomi di una lettera ammessi, tranne i bersagli di ``for`` e delle
  comprehension;
- ``extend_all``: tutti i nomi di una lettera.

Un nome di una lettera esteso prende il suffisso di §4.2 punto 4 (``n = 0`` → ``n_count``).
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from multimark._astindex import AstIndex
from multimark.cli.inventory import main as inventory_main
from multimark.config import Config, mcss_profile, multimark_base
from multimark.detect import detect
from multimark.embed import embed
from multimark.inventory import inventory_code
from multimark.layout import build_layout
from multimark.names import SINGLE_LETTER_MODES, name_sites, read_style
from multimark.synthetic import generate

CODE = """\
def f(data):
    n = 0
    s = ""
    total_count = 0
    for i in range(3):
        n += i
    for v in data:
        total_count += v
    m = [k for k in data]
    q = [q for q in data]
    return n, s, total_count, m
"""

MODULE_CODE = """\
x = 3
for j in range(x):
    pass
y = [z for z in range(x)]
"""


def _names(code: str, mode: str, module_level: bool = False) -> list[str]:
    sites = name_sites(AstIndex.from_code(code), module_level=module_level, single_letter=mode)
    return [s.name for s in sites]


def test_sites_by_mode() -> None:
    assert _names(CODE, "exclude") == ["total_count"]
    # i e v: bersagli di for; q: anche bersaglio di una comprehension; k: solo comprehension (a)
    assert _names(CODE, "extend_except_loop") == ["n", "s", "total_count", "m"]
    assert _names(CODE, "extend_all") == ["n", "s", "total_count", "i", "v", "m", "q"]
    with pytest.raises(ValueError):
        _names(CODE, "other")


def test_module_level_sites_by_mode() -> None:
    assert _names(MODULE_CODE, "exclude", module_level=True) == []
    assert _names(MODULE_CODE, "extend_except_loop", module_level=True) == ["x", "y"]
    assert _names(MODULE_CODE, "extend_all", module_level=True) == ["x", "j", "y"]


def test_underscore_and_self_stay_excluded() -> None:
    code = "def f(self):\n    _ = 1\n    a = self\n    return a\n"
    assert _names(code, "extend_all") == ["a"]


def test_config_defaults_and_validation() -> None:
    assert multimark_base().names_single_letter == "exclude"
    assert mcss_profile().names_single_letter == "exclude"
    for mode in SINGLE_LETTER_MODES:
        assert Config(names_single_letter=mode).names_single_letter == mode
    with pytest.raises(ValueError):
        Config(names_single_letter="all")


def test_inventory_counts_by_mode() -> None:
    rows = {m: inventory_code(CODE, single_letter=m) for m in SINGLE_LETTER_MODES}
    assert [rows[m]["n_vars"] for m in SINGLE_LETTER_MODES] == [1, 4, 7]
    assert rows["extend_all"]["n_bits_v1"] == rows["extend_all"]["n_sites_structural"] + 14


def test_inventory_cli_single_letter(tmp_path: Path) -> None:
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps({"code": CODE}) + "\n", encoding="utf-8")
    for mode, expected in zip(SINGLE_LETTER_MODES, (1, 4, 7)):
        out = tmp_path / f"rows_{mode}.jsonl"
        js = tmp_path / f"s_{mode}.json"
        args = ["--input", str(inp), "--output", str(out), "--summary-json", str(js),
                "--single-letter", mode]  # fmt: skip
        assert inventory_main(args) == 0
        assert json.loads(out.read_text(encoding="utf-8").splitlines()[0])["n_vars"] == expected
        assert json.loads(js.read_text(encoding="utf-8"))["options"]["single_letter"] == mode
    with pytest.raises(SystemExit):
        inventory_main(["--input", str(inp), "--single-letter", "all"])


def test_v1_extends_with_type_suffix() -> None:
    cfg = mcss_profile().with_(names_single_letter="extend_except_loop")
    msg = [random.Random(3).getrandbits(1) for _ in range(24)]
    r = embed(CODE, msg, 77, cfg)
    sites = name_sites(AstIndex.from_code(r.code), include_params=True,
                       single_letter="extend_except_loop")  # fmt: skip
    names = {s.name for s in sites}
    # n e s diventano nomi di due parole con il suffisso dal tipo del primo binding
    assert any(n.lower().replace("_", "") == "ncount" for n in names)
    assert any(n.lower().replace("_", "") == "sstr" for n in names)
    assert "i" in r.code and "for v in data" in r.code  # bersagli di for non toccati
    assert all(read_style(n) is not None for n in names if n not in ("data",))


def test_v2_tries_type_suffix_first() -> None:
    cfg = multimark_base().with_(names_single_letter="extend_all")
    renamed: set[str] = set()
    for key in range(40):
        msg = [random.Random(key).getrandbits(1) for _ in range(24)]
        r = embed("def f(a):\n    n = 0\n    return n + a\n", msg, key, cfg)
        idx = AstIndex.from_code(r.code)
        renamed.update(s.name for s in name_sites(idx, single_letter="extend_all"))
    assert "n" in renamed and "n_count" in renamed


SL_CODE = """\
def g(data, flag):
    n = len(data)
    s = ""
    t = []
    for i in range(0, n):
        t.append(data[i] * 2)
    w = [x for x in data if x is not None]
    if flag:
        r = n + 1
    else:
        r = 0
    return n, s, t, w, r


def h(values):
    a = 0
    b = 1.5
    for v in values:
        a += v
    c = a if a > 0 else b
    return c
"""


def _fragments() -> list[str]:
    out = [SL_CODE]
    for seed in range(6):
        out.append(generate(seed, 18, 2) + "\n\n" + SL_CODE)
    return out


@pytest.mark.parametrize("mode", ["extend_except_loop", "extend_all"])
@pytest.mark.parametrize("profile", ["multimark", "mcss"])
def test_roundtrip_single_letter(profile: str, mode: str) -> None:
    base = multimark_base() if profile == "multimark" else mcss_profile()
    cfg = base.with_(names_single_letter=mode)
    method = "mcss" if profile == "mcss" else "multimark"
    n_decoded = 0
    for i, code in enumerate(_fragments()):
        for key in range(1000 + 10 * i, 1006 + 10 * i):
            msg = [random.Random(key).getrandbits(1) for _ in range(cfg.message_bits)]
            r = embed(code, msg, key, cfg)
            assert r.status in ("OK", "PARTIAL"), (r.reason, r.extra.get("error"))
            assert r.extra["skipped_sites"] == 0
            n_before = build_layout(AstIndex.from_code(code), cfg, key).n_bits
            layout = build_layout(AstIndex.from_code(r.code), cfg, key)
            assert layout.n_bits == n_before  # stessi siti prima e dopo
            d = detect(r.code, msg, key, cfg, registry_sizes=(1,), method=method)
            assert d.extra["agreement"] == d.extra["n_votes"] - r.extra["n_names_wrong"]
            expected = "".join(map(str, msg))
            if r.extra["n_names_wrong"] == 0:
                assert d.decoded_message in (None, expected)
                covered = {j for s in layout.slots for j in s.indices}
                if len(covered) == cfg.codeword_length:
                    assert d.decoded_message == expected
            n_decoded += d.decoded_message == expected
    assert n_decoded > 0


def test_more_name_sites_with_extension() -> None:
    for base in (multimark_base(), mcss_profile()):
        counts = [
            len(
                build_layout(
                    AstIndex.from_code(SL_CODE), base.with_(names_single_letter=m), 5
                ).names
            )  # fmt: skip
            for m in SINGLE_LETTER_MODES
        ]
        assert counts[0] < counts[1] < counts[2]
