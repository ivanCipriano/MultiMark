"""Opzione ``canonical.same_kind = binding_order`` (§3.11 [v1.3.2], MD28): nei canali 2 e 3 un
confronto fra due ``Name`` è un sito, con forma canonica dall'ordine dei primi binding.

Proprietà verificate:

- lettura: parametri prima delle variabili locali, poi ordine di visita del primo binding; nessun
  sito senza binding nello scope dell'unità, con la stessa variabile, con variabili di
  comprehension o di un ciclo ``list_comp``, con un primo binding ``NamedExpr``;
- non interferenza: per tutte le ``2^k`` scritture dei siti l'insieme dei siti resta quello di
  partenza e ogni sito rilegge il valore scritto;
- indipendenza dai nomi: una rinomina coerente di tutte le variabili non cambia nessun bit letto;
- inserimento e rilevazione con l'opzione attiva (e con 2 bit per nome).
"""

from __future__ import annotations

import ast
import itertools
import json
import random
import textwrap
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from multimark._astindex import AstIndex
from multimark.channels import ReadOptions
from multimark.config import Config, mcss_profile, multimark_base
from multimark.detect import detect
from multimark.embed import embed
from multimark.layout import build_layout
from multimark.rewrite import WriteRequest, write_structural
from multimark.sites import find_sites
from multimark.synthetic import generate
from tests.renaming import rename_all_variables

BO = ReadOptions(same_kind="binding_order")
FIXTURE = Path(__file__).parent / "fixtures" / "p2_failures.jsonl"
SETTINGS = settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def _compares(code: str, options: ReadOptions = BO) -> list[tuple[str, int]]:
    sites = find_sites(AstIndex.from_code(textwrap.dedent(code).lstrip("\n")), options)
    return [
        (ast.unparse(s.node), s.value)
        for s in sites
        if s.channel in ("compare_dir", "equality_dir")
    ]


# ---------------------------------------------------------------------- lettura


def test_order_params_then_visit_order() -> None:
    code = """
        def f(a, b):
            c = a
            d = b
            return a < b, b < a, c == a, a != c, d >= c, c > d
        """
    # ordine di uscita di §3.9: prima il canale 2, poi il 3
    assert _compares(code) == [
        ("a < b", 0), ("b < a", 1), ("d >= c", 1), ("c > d", 0), ("c == a", 1), ("a != c", 0),
    ]  # fmt: skip


def test_off_keeps_name_pairs_out() -> None:
    code = "def f(a, b):\n    return a < b, a == b\n"
    assert _compares(code, ReadOptions()) == []
    assert len(_compares(code)) == 2


def test_parameters_before_locals_across_scopes() -> None:
    # ``t`` è legato prima della ``lambda``, ma ``p`` è un parametro: viene prima
    code = """
        def f(a):
            t = a
            h = lambda p: p < t
            def g(b):
                return t < b
            return h, g
        """
    assert _compares(code) == [("p < t", 0), ("t < b", 1)]


def test_module_level_code() -> None:
    code = "n = int(input())\nm = n + 1\nprint(n < m, m == n)\n"
    assert _compares(code) == [("n < m", 0), ("m == n", 1)]


@pytest.mark.parametrize(
    "code",
    [
        "N = 3\n\n\ndef f(a):\n    return a < N\n",  # nome di modulo letto in una funzione
        "def f(a):\n    return a < len\n",  # builtin
        "def f(a):\n    return a < zeta\n",  # non definito
        "def f(a):\n    return a == a\n",  # stessa variabile
        "def f(a):\n    global g\n    g = 1\n    return a < g\n",  # global
        "def f(a):\n    import os\n    os = a\n    return a < os\n",  # binding non di variabile
        "def f(a):\n    def g():\n        pass\n    return a == g\n",  # def
        "class C:\n    u = 1\n    v = 2\n    w = u < v\n",  # attributi di classe
        "def f(xs, y):\n    return [x < y for x in xs]\n",  # variabile di comprehension
        # bersaglio di un ciclo con il solo append (forma 0 di list_comp)
        "def f(xs, y):\n    out = []\n    for x in xs:\n        out.append(x < y)\n"
        "    return out\n",
        # primo binding NamedExpr
        "def f(a):\n    if (m := a):\n        x = 1\n    else:\n        x = 2\n    return x < m\n",
    ],
)
def test_not_a_site(code: str) -> None:
    assert _compares(code) == []


def test_loop_target_outside_append_loop_is_a_site() -> None:
    code = (
        "def f(n, k):\n    for i in range(n):\n        if i < k:\n            k = i\n    return k\n"
    )
    assert _compares(code) == [("i < k", 1)]


def test_options_validation() -> None:
    with pytest.raises(ValueError):
        ReadOptions(same_kind="text")
    with pytest.raises(ValueError):
        ReadOptions(canonical="paper", same_kind="binding_order")
    with pytest.raises(ValueError):
        mcss_profile().with_(canonical_same_kind="binding_order")
    cfg = multimark_base().with_(canonical_same_kind="binding_order")
    assert cfg.read_options.same_kind == "binding_order"
    assert multimark_base().canonical_same_kind == mcss_profile().canonical_same_kind == "off"


# ---------------------------------------------------------------------- 2^k scritture

COMBOS = {
    # ternario con NamedExpr nella condizione: la forma 1 sposta ``x`` prima di ``m``
    "ternary_walrus": """
        def f(a, b):
            if (m := a + 1):
                x = a
            else:
                x = b
            return x < m, x < b, a <= b
        """,
    # list_comp nelle due forme con confronti nell'elemento
    "list_comp_compares": """
        def f(xs, y):
            w = y
            out = []
            for x in xs:
                out.append(w < y)
            res = [y == z for z in xs]
            return out, res, y > w
        """,
    # else_return e nested_if che spostano confronti fra variabili
    "else_return_nested_if": """
        def f(a, b, c):
            t = a + 1
            if c is None:
                return t
            else:
                if a:
                    if b:
                        t = b
                return t >= a
        """,
    # aug_assign, range_zero e confronti dentro un for
    "aug_and_loop": """
        def f(a, b):
            s = 0
            s = s + 1
            for i in range(0, a):
                if i < b:
                    s += 2
            return s == b
        """,
    # funzione annidata e lambda
    "nested_scopes": """
        def f(a, b):
            def g(c):
                return c < a, a == b
            h = lambda p: p > b
            return g, h
        """,
    # codice di modulo
    "module_code": """
        n = int(input())
        m = n + 1
        if n < m:
            k = m
        else:
            k = n
        print(k != n, m * m)
        """,
}


@pytest.mark.parametrize("name", list(COMBOS))
def test_all_writes_keep_site_set(name: str) -> None:
    code = textwrap.dedent(COMBOS[name]).lstrip("\n")
    index = AstIndex.from_code(code)
    sites = find_sites(index, BO)
    keys = [s.key for s in sites]
    assert any(isinstance(s.node, ast.Compare) and isinstance(s.node.left, ast.Name)
               and isinstance(s.node.comparators[0], ast.Name) for s in sites), name  # fmt: skip
    assert 2 <= len(sites) <= 10, (name, keys)
    for bits in itertools.product((0, 1), repeat=len(sites)):
        new, unwritable = write_structural(
            code, index, [WriteRequest(s, b) for s, b in zip(sites, bits)]
        )
        assert not unwritable, (name, bits)
        after = find_sites(AstIndex.from_code(new), BO)
        assert [s.key for s in after] == keys, (name, bits, new)
        assert [s.value for s in after] == list(bits), (name, bits, new)


# ---------------------------------------------------------------------- rinomina


def _reading(code: str, options: ReadOptions) -> list[tuple]:
    return [(s.key, s.value) for s in find_sites(AstIndex.from_code(code), options)]


def _check_renaming(code: str, seed: int) -> None:
    """Per nome: nessun bit cambia, in nessun canale. Per variabile (omonime separate): nessun bit
    cambia fuori da ``list_comp``, la cui condizione su ``x`` (MD12) dipende per costruzione dai
    nomi (la forma col ciclo lega ``x`` nello scope della funzione)."""
    by_name, _ = rename_all_variables(code, seed, split_scopes=False)
    by_var, _ = rename_all_variables(code, seed, split_scopes=True)
    for options in (ReadOptions(), BO):
        base = _reading(code, options)
        assert _reading(by_name, options) == base, (options.same_kind, by_name)
        keep = [r for r in base if r[0][2] != "list_comp"]
        assert [r for r in _reading(by_var, options) if r[0][2] != "list_comp"] == keep, (
            options.same_kind,
            by_var,
        )


@SETTINGS
@given(
    seed=st.integers(0, 10**6),
    n_statements=st.integers(3, 30),
    n_functions=st.integers(1, 3),
    rename_seed=st.integers(0, 10**6),
)
def test_renaming_keeps_every_bit_synthetic(
    seed: int, n_statements: int, n_functions: int, rename_seed: int
) -> None:
    code = generate(seed, n_statements, n_functions, name_compares=True)
    _check_renaming(code, rename_seed)


@SETTINGS
@given(rename_seed=st.integers(0, 10**6))
def test_renaming_keeps_every_bit_combos(rename_seed: int) -> None:
    for code in COMBOS.values():
        _check_renaming(textwrap.dedent(code).lstrip("\n"), rename_seed)


def test_renaming_keeps_every_bit_fixture() -> None:
    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    for i, row in enumerate(rows):
        _check_renaming(row["original_code"], i)


def test_renaming_actually_changes_names() -> None:
    code = textwrap.dedent(COMBOS["nested_scopes"]).lstrip("\n")
    new, n = rename_all_variables(code, 1)
    assert n == 5 and "zq" in new and " a " not in new  # a, b, c, p, h (g è un def)
    # c < a, p > b (canale 2), a == b (canale 3)
    assert [v for _, v in _compares(new)] == [v for _, v in _compares(code)] == [1, 1, 0]


# ---------------------------------------------------------------------- inserimento


def _roundtrip(code: str, key: int, cfg: Config) -> None:
    msg = [random.Random(key).getrandbits(1) for _ in range(cfg.message_bits)]
    r = embed(code, msg, key, cfg)
    assert r.status in ("OK", "PARTIAL"), (r.reason, r.extra.get("error"))
    assert r.extra["skipped_sites"] == 0
    d = detect(r.code, msg, key, cfg, registry_sizes=(1,))
    assert d.extra["agreement"] == d.extra["n_votes"] - r.extra["n_names_wrong"]
    expected = "".join(map(str, msg))
    if r.extra["n_names_wrong"] == 0:
        assert d.decoded_message in (None, expected)
        layout = build_layout(AstIndex.from_code(r.code), cfg, key)
        if len({i for s in layout.slots for i in s.indices}) == cfg.codeword_length:
            assert d.decoded_message == expected


@SETTINGS
@given(
    seed=st.integers(0, 10**6),
    n_statements=st.integers(3, 40),
    n_functions=st.integers(1, 3),
    key=st.integers(0, 2**31 - 1),
    bits_per_name=st.sampled_from([1, 2]),
)
def test_roundtrip_with_binding_order(
    seed: int, n_statements: int, n_functions: int, key: int, bits_per_name: int
) -> None:
    cfg = multimark_base().with_(
        canonical_same_kind="binding_order", names_bits_per_name=bits_per_name
    )
    _roundtrip(generate(seed, n_statements, n_functions, name_compares=True), key, cfg)


@pytest.mark.parametrize("name", list(COMBOS))
def test_roundtrip_combos(name: str) -> None:
    cfg = multimark_base().with_(canonical_same_kind="binding_order", names_bits_per_name=2)
    for key in range(6):
        _roundtrip(textwrap.dedent(COMBOS[name]).lstrip("\n"), key, cfg)


def test_more_sites_than_off() -> None:
    code = generate(7, 30, 2, name_compares=True)
    off = find_sites(AstIndex.from_code(code), ReadOptions())
    on = find_sites(AstIndex.from_code(code), BO)
    assert len(on) > len(off)
    assert {(s.key, s.value) for s in off if s.channel not in ("compare_dir", "equality_dir")} == {
        (s.key, s.value) for s in on if s.channel not in ("compare_dir", "equality_dir")
    }


def test_synthetic_default_unchanged() -> None:
    # senza name_compares i frammenti sono quelli di sempre (log di P1 e test esistenti)
    assert generate(3, 12, 2) == generate(3, 12, 2, name_compares=False)
    assert " < flag" not in generate(3, 12, 2)


# ---------------------------------------------------------------------- inventario


def test_inventory_same_kind() -> None:
    from multimark.inventory import inventory_code

    code = "def f(a, b):\n    c = a\n    return a < b, c == b\n"
    off = inventory_code(code)
    on = inventory_code(code, same_kind="binding_order")
    assert (off["n_sites_compare_dir"], off["n_sites_equality_dir"]) == (0, 0)
    assert (on["n_sites_compare_dir"], on["n_sites_equality_dir"]) == (1, 1)
    assert on["n_sites_total"] == off["n_sites_total"] + 2


def test_inventory_cli_same_kind(tmp_path: Path) -> None:
    from multimark.cli.inventory import main

    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps({"code": "def f(a, b):\n    return a < b\n"}) + "\n")
    js = tmp_path / "s.json"
    args = ["--input", str(inp), "--summary-json", str(js), "--summary", str(tmp_path / "s.txt")]
    assert main([*args, "--same-kind", "binding_order"]) == 0
    summary = json.loads(js.read_text(encoding="utf-8"))
    assert summary["options"]["same_kind"] == "binding_order"
    assert "same_kind=binding_order" in (tmp_path / "s.txt").read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        main([*args, "--same-kind", "binding_order", "--canonical", "paper"])
