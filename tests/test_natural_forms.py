"""Opzione ``canonical.natural_forms`` (§3.11 [v1.3.9], MD29): nessun sito con un operando costante
nei canali 2, 3 e 6; con ``const_left_zero`` anche nessun sito ``range_zero`` né ``slice_lower``.

Proprietà verificate:

- lettura: costanti semplici, negative, espressioni costanti, stringhe; costante a sinistra o a
  destra nell'originale; i confronti senza costanti restano siti;
- non interferenza: per tutte le ``2^k`` scritture l'insieme dei siti resta quello di partenza;
- nessun codice marcato ha un confronto o un ``+``/``*`` con la costante a sinistra in più
  dell'originale;
- con ``off`` la lettura è quella di prima; con l'opzione si tolgono solo siti;
- inserimento e rilevazione, inventario, ``Config``.
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
from multimark.channels import ReadOptions, is_constant_expr
from multimark.cli import inventory as inventory_cli
from multimark.config import Config, mcss_profile, multimark_base
from multimark.detect import detect
from multimark.embed import embed
from multimark.inventory import inventory_code
from multimark.layout import build_layout
from multimark.rewrite import WriteRequest, write_structural
from multimark.sites import find_sites
from multimark.synthetic import generate
from tests.test_same_kind_binding_order import COMBOS

CL = ReadOptions(natural_forms="const_left")
CLZ = ReadOptions(natural_forms="const_left_zero")
FIXTURE = Path(__file__).parent / "fixtures" / "p2_failures.jsonl"
SETTINGS = settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def _src(code: str) -> str:
    return textwrap.dedent(code).lstrip("\n")


def _channels(code: str, options: ReadOptions) -> list[str]:
    return [s.channel for s in find_sites(AstIndex.from_code(_src(code)), options)]


# ---------------------------------------------------------------------- lettura


@pytest.mark.parametrize(
    "expr",
    ["0", "-1", "+2", "10**9 + 7", "'a'", "3.5", "(1, 2)", "-(2 * 3)"],
)
def test_constant_expressions(expr: str) -> None:
    assert is_constant_expr(ast.parse(expr, mode="eval").body)


@pytest.mark.parametrize("expr", ["x", "-x", "x + 1", "f(1)", "a[0]", "(1, x)", "len(a)"])
def test_non_constant_expressions(expr: str) -> None:
    assert not is_constant_expr(ast.parse(expr, mode="eval").body)


@pytest.mark.parametrize(
    "compare",
    ["x < 10", "10 > x", "x == 0", "0 == x", "x >= -1", "x < 10**9 + 7", "s != 'a'", "'a' == s"],
)
def test_compare_with_constant_is_not_a_site(compare: str) -> None:
    code = f"def f(x, s):\n    return {compare}\n"
    assert _channels(code, ReadOptions()) in (["compare_dir"], ["equality_dir"])
    assert _channels(code, CL) == _channels(code, CLZ) == []


@pytest.mark.parametrize("compare", ["x < len(a)", "a[0] == x", "f(x) >= x.y", "x + 1 < len(a)"])
def test_compare_without_constant_stays(compare: str) -> None:
    code = f"def f(x, a):\n    return {compare}\n"
    compares = [c for c in _channels(code, CL) if c in ("compare_dir", "equality_dir")]
    assert len(compares) == 1, compare
    # ``x + 1`` dentro l'operando non è più un sito operand_order, il confronto sì
    assert "operand_order" not in _channels(code, CL)


def test_operand_order_with_constant_is_not_a_site() -> None:
    code = "def f(n, a):\n    return n + 1, 2 * a[0], a.x * 3\n"
    assert _channels(code, ReadOptions()).count("operand_order") == 3
    assert "operand_order" not in _channels(code, CL)


def test_operand_order_sites_always_have_a_constant() -> None:
    """Ogni sito ``operand_order`` ha per definizione una costante numerica da un lato (§3.3.1),
    quindi con l'opzione attiva il canale resta vuoto anche sulla fixture."""
    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    total = 0
    for code in {r["original_code"] for r in rows}:
        index = AstIndex.from_code(code)
        base = [s for s in find_sites(index, ReadOptions()) if s.channel == "operand_order"]
        total += len(base)
        nodes = [s.node for s in base if isinstance(s.node, ast.BinOp)]
        assert len(nodes) == len(base)
        assert all(is_constant_expr(n.left) or is_constant_expr(n.right) for n in nodes)
        assert not [s for s in find_sites(index, CL) if s.channel == "operand_order"]
    assert total > 0


def test_range_and_slice_by_mode() -> None:
    code = "def f(a, n):\n    for i in range(0, n):\n        a = a[0:i] + a[:n]\n    return a\n"
    for options in (ReadOptions(), CL):
        chans = _channels(code, options)
        assert chans.count("range_zero") == 1 and chans.count("slice_lower") == 2
    chans = _channels(code, CLZ)
    assert "range_zero" not in chans and "slice_lower" not in chans


def test_other_channels_unchanged() -> None:
    code = """
    def f(a, b):
        s = 0
        s = s + b
        out = []
        for x in a:
            out.append(x * x)
        if b is None:
            return None
        return out
    """
    assert _channels(code, CLZ) == _channels(code, ReadOptions())


def test_validation() -> None:
    with pytest.raises(ValueError):
        ReadOptions(natural_forms="all")
    with pytest.raises(ValueError):
        ReadOptions(canonical="paper", natural_forms="const_left")
    with pytest.raises(ValueError):
        Config(canonical_natural_forms="x")
    for mode in ("const_left", "const_left_zero"):
        with pytest.raises(ValueError):
            mcss_profile().with_(canonical_natural_forms=mode)
        assert (
            multimark_base().with_(canonical_natural_forms=mode).read_options.natural_forms == mode
        )
    assert (
        multimark_base().canonical_natural_forms == mcss_profile().canonical_natural_forms == "off"
    )


# ---------------------------------------------------------------------- 2^k scritture

EXTRA_COMBOS = {
    # confronti con costante accanto a square, list_comp, operand_order dentro un operando
    "constants_and_square": """
        def f(a, n):
            out = []
            for x in a:
                out.append(x * x)
            if n * n > len(a):
                return out
            return [y for y in a if y > 0], n + 1 < len(a)
        """,
    "constants_and_ranges": """
        def f(a, n):
            s = 0
            for i in range(0, n):
                if a[i] == 0:
                    s += 1
            t = a[0:n]
            return s, t, n * 2 < len(t)
        """,
}


@pytest.mark.parametrize("mode", ["const_left", "const_left_zero"])
@pytest.mark.parametrize("name", [*COMBOS, *EXTRA_COMBOS])
def test_all_writes_keep_site_set(name: str, mode: str) -> None:
    options = ReadOptions(natural_forms=mode)
    code = _src({**COMBOS, **EXTRA_COMBOS}[name])
    index = AstIndex.from_code(code)
    sites = find_sites(index, options)
    keys = [s.key for s in sites]
    assert len(sites) <= 10, (name, keys)
    if name in EXTRA_COMBOS:
        assert sites, name
    for bits in itertools.product((0, 1), repeat=len(sites)):
        new, unwritable = write_structural(
            code, index, [WriteRequest(s, b) for s, b in zip(sites, bits)]
        )
        assert not unwritable, (name, bits)
        after = find_sites(AstIndex.from_code(new), options)
        assert [s.key for s in after] == keys, (name, bits, new)
        assert [s.value for s in after] == list(bits), (name, bits, new)


def test_none_check_keeps_none_on_the_right() -> None:
    code = "def f(a, b):\n    if a is None:\n        return b == None\n    return a is not None\n"
    index = AstIndex.from_code(code)
    sites = [s for s in find_sites(index, CL) if s.channel == "none_check"]
    assert len(sites) == 3
    for bits in itertools.product((0, 1), repeat=len(sites)):
        new, _ = write_structural(code, index, [WriteRequest(s, b) for s, b in zip(sites, bits)])
        for node in ast.walk(ast.parse(new)):
            if isinstance(node, ast.Compare):
                assert not (isinstance(node.left, ast.Constant) and node.left.value is None), new


# ---------------------------------------------------------------------- inserimento


def _const_left(code: str) -> int:
    """Confronti e ``+``/``*`` con la costante a sinistra e l'altro operando non costante."""
    n = 0
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            left, right = node.left, node.comparators[0]
        elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mult)):
            left, right = node.left, node.right
        else:
            continue
        n += int(is_constant_expr(left) and not is_constant_expr(right))
    return n


def _range_zero(code: str) -> int:
    return sum(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "range"
        and len(n.args) == 2 and isinstance(n.args[0], ast.Constant) and n.args[0].value == 0
        for n in ast.walk(ast.parse(code))
    )  # fmt: skip


@SETTINGS
@given(
    seed=st.integers(0, 10**6),
    n_statements=st.integers(3, 40),
    n_functions=st.integers(1, 3),
    key=st.integers(0, 2**31 - 1),
    mode=st.sampled_from(["const_left", "const_left_zero"]),
    bits_per_name=st.sampled_from([1, 2]),
)
def test_marked_code_adds_no_constant_on_the_left(
    seed: int, n_statements: int, n_functions: int, key: int, mode: str, bits_per_name: int
) -> None:
    code = generate(seed, n_statements, n_functions)
    cfg = multimark_base().with_(canonical_natural_forms=mode, names_bits_per_name=bits_per_name)
    msg = [random.Random(key).getrandbits(1) for _ in range(cfg.message_bits)]
    r = embed(code, msg, key, cfg)
    assert r.status in ("OK", "PARTIAL", "FAILED")
    if r.status == "FAILED":
        assert r.reason == "no_sites", r.reason
        return
    assert r.extra["skipped_sites"] == 0
    assert _const_left(r.code) <= _const_left(code), r.code
    if mode == "const_left_zero":
        assert _range_zero(r.code) == _range_zero(code)
    d = detect(r.code, msg, key, cfg, registry_sizes=(1,))
    assert d.extra["agreement"] == d.extra["n_votes"] - r.extra["n_names_wrong"]


@pytest.mark.parametrize("mode", ["const_left", "const_left_zero"])
@pytest.mark.parametrize("name", list(EXTRA_COMBOS))
def test_roundtrip(name: str, mode: str) -> None:
    code = _src(EXTRA_COMBOS[name])
    cfg = multimark_base().with_(canonical_natural_forms=mode)
    for key in range(5):
        msg = [random.Random(key).getrandbits(1) for _ in range(cfg.message_bits)]
        r = embed(code, msg, key, cfg)
        assert r.status in ("OK", "PARTIAL"), r.reason
        d = detect(r.code, msg, key, cfg, registry_sizes=(1,))
        assert d.extra["agreement"] == d.extra["n_votes"] - r.extra["n_names_wrong"]
        assert _const_left(r.code) <= _const_left(code)


def test_only_removes_sites_on_fixture() -> None:
    """Con l'opzione si tolgono siti: quelli che restano hanno valore di ``off``, e ``off`` legge
    come prima. Unica eccezione: un ciclo ``list_comp`` che MD23 escludeva perché ``expr`` e
    ``it`` contenevano candidati dello stesso canale (es. due confronti con costante) può diventare
    un sito, perché quei candidati non ci sono più."""
    rows = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    removed = 0
    for code in sorted({r["original_code"] for r in rows}):
        index = AstIndex.from_code(code)
        base = {(s.channel, id(s.node)): s.value for s in find_sites(index, ReadOptions())}
        assert base == {
            (s.channel, id(s.node)): s.value
            for s in find_sites(index, ReadOptions(natural_forms="off"))
        }
        for options in (CL, CLZ):
            got = {(s.channel, id(s.node)): s.value for s in find_sites(index, options)}
            kept = {k: v for k, v in got.items() if k[0] != "list_comp" or k in base}
            assert kept.items() <= base.items()
            removed += len(base) - len(kept)
    assert removed > 0


def test_list_comp_freed_by_md23() -> None:
    code = _src(
        """
        def f(a):
            out = []
            for x in range(a > 0):
                out.append(x < 1)
            return out
        """
    )
    off = _channels(code, ReadOptions())
    on = _channels(code, CL)
    assert "list_comp" not in off and "list_comp" in on
    assert "compare_dir" in off and "compare_dir" not in on


def test_layout_uses_option() -> None:
    code = "def f(x, a):\n    if x < 10:\n        return x < len(a)\n    return 0\n"
    index = AstIndex.from_code(code)
    off = build_layout(index, multimark_base(), 3)
    on = build_layout(index, multimark_base().with_(canonical_natural_forms="const_left"), 3)
    assert len(off.structural) == len(on.structural) + 1


# ---------------------------------------------------------------------- inventario


def test_inventory_natural_forms() -> None:
    code = "def f(a, n):\n    for i in range(0, n):\n        if a[i] == 0:\n            n = n + 1\n    return n < len(a)\n"  # noqa: E501
    off = inventory_code(code)
    cl = inventory_code(code, natural_forms="const_left")
    clz = inventory_code(code, natural_forms="const_left_zero")
    assert off["n_sites_structural"] > cl["n_sites_structural"] > clz["n_sites_structural"]
    assert cl["n_sites_operand_order"] == 0 and off["n_sites_operand_order"] == 0
    assert (off["n_sites_range_zero"], cl["n_sites_range_zero"], clz["n_sites_range_zero"]) == (
        1, 1, 0,
    )  # fmt: skip


def test_inventory_cli_natural_forms(tmp_path: Path) -> None:
    inp = tmp_path / "in.jsonl"
    inp.write_text(json.dumps({"code": "def f(x):\n    return x < 1, x < len(x)\n"}) + "\n")
    js = tmp_path / "s.json"
    txt = tmp_path / "s.txt"
    args = ["--input", str(inp), "--summary-json", str(js), "--summary", str(txt)]
    assert inventory_cli.main([*args, "--natural-forms", "const_left"]) == 0
    assert json.loads(js.read_text(encoding="utf-8"))["options"]["natural_forms"] == "const_left"
    assert "natural_forms=const_left" in txt.read_text(encoding="utf-8")
    # senza l'opzione il riepilogo resta quello di prima
    assert inventory_cli.main(args) == 0
    assert "natural_forms" not in json.loads(js.read_text(encoding="utf-8"))["options"]
    assert "natural_forms" not in txt.read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        inventory_cli.main([*args, "--natural-forms", "const_left", "--canonical", "paper"])
