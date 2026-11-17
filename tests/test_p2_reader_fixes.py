"""Correzioni MD20–MD25 (casi del criterio (a) di P2): un sito esiste solo se lo scrittore può
dargli ogni valore e la rilettura lo ritrova; la regola dipende solo dal codice letto."""

from __future__ import annotations

import itertools
import random
from pathlib import Path

import pytest

from multimark._astindex import AstIndex
from multimark.channels import ReadOptions
from multimark.config import mcss_profile, multimark_base
from multimark.detect import detect
from multimark.embed import embed
from multimark.layout import build_layout
from multimark.names import (
    RETRY_SUFFIXES,
    TYPE_SUFFIXES,
    name_sites,
    render_style,
    segments,
    style_writable,
)
from multimark.rewrite import WriteRequest, write_structural
from multimark.sites import find_sites


def _texts(code: str, channel: str, options: ReadOptions) -> list[str]:
    import ast

    return [
        ast.unparse(s.node)
        for s in find_sites(AstIndex.from_code(code), options)
        if s.channel == channel
    ]


# ---------------------------------------------------------------------- MD20: nomi a stili


@pytest.mark.parametrize(
    "name", ["count_3", "min_1", "X_1", "i_2", "check_3", "tR", "c_k", "x_ys_1"]
)
def test_style_not_writable(name: str) -> None:
    assert not style_writable(name)


@pytest.mark.parametrize("name", ["XYs", "Yes", "total_count", "nCount", "a", "N", "x1", "rowCol"])
def test_style_writable(name: str) -> None:
    assert style_writable(name)
    segs = segments(name)
    if len(segs) < 2:
        segs = [*segs, "val"]
    for style in range(4):
        assert style_writable(render_style(segs, style))  # la regola vale anche sul marcato


def test_v1b_needs_only_snake_and_camel() -> None:
    assert style_writable("c_k", (0, 1))  # c_k, cK
    assert not style_writable("c_k", (0, 1, 2, 3))  # CK non si rilegge con due segmenti


def test_style_rule_only_for_style_variants() -> None:
    code = "def f(d):\n    count_3 = 1\n    total_count = 2\n    return count_3 + total_count\n"
    index = AstIndex.from_code(code)
    assert [s.name for s in name_sites(index)] == ["count_3", "total_count"]  # V2
    assert [s.name for s in name_sites(index, styles=(0, 1, 2, 3))] == ["total_count"]  # V1
    mcss = build_layout(index, mcss_profile(), 3)
    assert [s.name.name for s in mcss.names if s.name] == ["d", "total_count"]


def test_retry_suffixes_order() -> None:
    assert RETRY_SUFFIXES[: len(TYPE_SUFFIXES)] == TYPE_SUFFIXES
    assert len(set(RETRY_SUFFIXES)) == len(RETRY_SUFFIXES)


def test_conflict_tries_next_suffix() -> None:
    # ``q`` va esteso, ma ``q_val`` (e le sue rese) c'è già: si prova il suffisso successivo.
    code = "q_val = 1\nq = 2\nqVal = 3\nQVal = 4\nQ_VAL = 5\nprint(q, q_val, qVal, QVal, Q_VAL)\n"
    cfg = mcss_profile()
    for key in range(12):
        msg = [random.Random(key).getrandbits(1) for _ in range(24)]
        r = embed(code, msg, key, cfg)
        assert r.extra["n_names_unwritable"] == 0, key
        assert r.extra["n_names_wrong"] == 0 and r.extra["n_names_unread"] == 0, key


def test_module_single_letter_extended_despite_parameter() -> None:
    # Caso p00004: i parametri ``a, b`` di ``inverse`` e le variabili di modulo ``a, b``.
    code = (
        "def inverse(a, b):\n    return a - b\n\n\n"
        "while True:\n    a, b = [float(i) for i in input().split()]\n    print(inverse(a, b))\n"
    )
    cfg = mcss_profile()
    for key in range(12):
        msg = [random.Random(key).getrandbits(1) for _ in range(24)]
        r = embed(code, msg, key, cfg)
        assert r.extra["n_names_unwritable"] == 0 and r.extra["n_names_unread"] == 0, key


# ---------------------------------------------------------------------- MD21: empty_coll


def test_empty_literal_not_a_site_when_constructor_is_bound() -> None:
    code = "def dict(a):\n    d = {}\n    return d\n\n\ndef g():\n    return [], {}\n"
    assert _texts(code, "empty_coll", ReadOptions()) == ["[]"]
    assert _texts(code, "empty_coll", ReadOptions(guards=False)) == ["{}", "[]", "{}"]


# ---------------------------------------------------------------------- MD22: paper


def test_paper_tie_with_inner_site_is_not_a_site() -> None:
    code = "def f(a, b, c):\n    return a + b <= 2 * c, a + b <= c - b\n"
    paper = ReadOptions(canonical="paper", channels="mcss8")
    # ``2 * c`` è un sito operand_order: il confronto che lo contiene non ha più verso dal testo
    assert _texts(code, "compare_dir", paper) == ["a + b <= c - b"]
    assert _texts(code, "operand_order", paper) == ["2 * c"]


# ---------------------------------------------------------------------- MD23: list_comp


def test_list_comp_with_sites_in_element_and_iterable() -> None:
    code = "def f(n):\n    g = [[] for _ in range(n + 1)]\n    return g\n"
    positional = ReadOptions(canonical="paper", channels="mcss8", visit_order=True)
    assert _texts(code, "list_comp", positional) == []  # [] e n + 1: ordine di visita cambia
    assert _texts(code, "list_comp", ReadOptions(channels="mcss8")) == [
        "g = [[] for _ in range(n + 1)]"
    ]  # canali diversi: per il legame per funzione e canale l'ordine non conta
    same = "def f(a):\n    g = [x + 1 for x in a[0:3] + 1]\n    return g\n"
    assert _texts(same, "list_comp", ReadOptions()) == []  # operand_order in entrambi


# ---------------------------------------------------------------------- MD24: else_return


@pytest.mark.parametrize(
    "code",
    [
        # p03050 (f): l'else_return interno chiude il corpo di un altro else_return
        "def f(p, i):\n    if i:\n        t = 1\n        if t:\n            return 0\n"
        "        return t\n    return 2\n",
        # p03050 (main): l'else_return è la prima istruzione del corpo di un nested_if in forma 1
        "def g(n, i):\n    for i in range(n):\n        if n and i:\n            if n <= i:\n"
        "                break\n            n += i\n    return n\n",
        # primo elemento dell'orelse: in forma 0 diventerebbe un elif
        "def h(a, b):\n    if a:\n        b = 1\n    else:\n        if b:\n            return 1\n"
        "        b = 2\n    return b\n",
    ],
)
def test_else_return_inside_if_keeps_every_site(code: str) -> None:
    index = AstIndex.from_code(code)
    sites = find_sites(index, ReadOptions())
    keys = [s.key for s in sites]
    for bits in itertools.product((0, 1), repeat=len(sites)):
        new, unwritable = write_structural(
            code, index, [WriteRequest(s, b) for s, b in zip(sites, bits)]
        )
        assert not unwritable
        after = find_sites(AstIndex.from_code(new), ReadOptions())
        assert [s.key for s in after] == keys, (bits, new)
        assert [s.value for s in after] == list(bits), (bits, new)


# ---------------------------------------------------------------------- MD25: righe condivise


@pytest.mark.parametrize(
    "code, channel",
    [
        ("def f(d): t = [x for x in d]; return t\n", "list_comp"),
        ("def f(d):\n    y = 1; t = [x for x in d]\n    return t, y\n", "list_comp"),
        ("def f(d, c):\n    if c: t = [x for x in d]\n    return d\n", "list_comp"),
        ("def f(c, a, b): x = a if c else b; return x\n", "ternary"),
        ("def f(c, a, b):\n    q = 1; x = a if c else b\n    return x, q\n", "ternary"),
    ],
)
def test_shared_line_is_not_a_site(code: str, channel: str) -> None:
    assert _texts(code, channel, ReadOptions()) == []


def test_own_line_is_still_a_site() -> None:
    code = "def f(d, c, a, b):\n    t = [x for x in d]\n    y = a if c else b\n    return t, y\n"
    assert len(_texts(code, "list_comp", ReadOptions())) == 1
    assert len(_texts(code, "ternary", ReadOptions())) == 1


# ---------------------------------------------------------------------- fid duplicati


def test_duplicate_fid_functions_round_trip() -> None:
    # p03050: due funzioni ``main`` senza parametri; le chiavi ``(fid, canale, rango)`` coincidono
    code = (
        "def main():\n    ans = f(3)\n    print(ans)\n\n\n"
        "def f(x):\n    return x + 1\n\n\n"
        "def main():\n    ans = 0\n    for i in range(1, 9):\n        ans += i\n    print(ans)\n"
    )
    for cfg, method in ((mcss_profile(), "mcss"), (multimark_base(), "multimark")):
        for key in range(8):
            msg = [random.Random(key).getrandbits(1) for _ in range(24)]
            r = embed(code, msg, key, cfg)
            assert r.status in ("OK", "PARTIAL"), (method, key, r.extra.get("error"))
            assert r.extra["skipped_sites"] == 0
            d = detect(r.code, msg, key, cfg, registry_sizes=(1,), method=method)
            assert d.extra["agreement"] == d.extra["n_votes"] - r.extra["n_names_wrong"]


# ---------------------------------------------------------------------- inventario


def test_inventory_counts_mcss_rules() -> None:
    from multimark.inventory import inventory_code

    code = (
        "def f(n):\n    count_3 = 1\n    grid = [[] for _ in range(n + 1)]\n"
        "    return grid, count_3\n"
    )
    base = inventory_code(code, channels="mcss8")
    mcss = inventory_code(code, channels="mcss8", linking="positional", name_variant="V1")
    assert (base["n_sites_list_comp"], base["n_vars"]) == (1, 2)
    assert (mcss["n_sites_list_comp"], mcss["n_vars"]) == (0, 1)


def test_inventory_cli_mcss_rules(tmp_path: Path) -> None:
    import json

    from multimark.cli.inventory import main

    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps({"code": "def f():\n    count_3 = 1\n    return count_3\n"}) + "\n")
    js = tmp_path / "s.json"
    args = ["--input", str(inp), "--summary-json", str(js), "--summary", str(tmp_path / "s.txt")]
    assert main([*args, "--name-variant", "V1", "--linking", "positional"]) == 0
    options = json.loads(js.read_text(encoding="utf-8"))["options"]
    assert (options["name_variant"], options["linking"]) == ("V1", "positional")
