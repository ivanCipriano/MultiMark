"""Ricerca dei siti: visita, unità di funzione, fid, rango, ordine, sovrapposizioni (§3.2–3.4)."""

from __future__ import annotations

import ast

import pytest

from multimark._astindex import MODULE_UNIT, AstIndex, iter_preorder
from multimark.channels import CHANNELS
from multimark.sites import count_by_channel, find_sites_in_code
from tests.helpers import read, src


def test_preorder_matches_iter_child_nodes() -> None:
    tree = ast.parse("a = f(b, c[1]) + 2\nif x: y = [z for z in w]\n")

    def rec(node: ast.AST) -> list:
        out = [node]
        for child in ast.iter_child_nodes(node):
            out.extend(rec(child))
        return out

    assert [id(n) for n in iter_preorder(tree)] == [id(n) for n in rec(tree)]
    assert [id(n) for n in AstIndex(tree).order] == [id(n) for n in rec(tree)]


def test_function_of_is_outermost_function() -> None:
    code = src(
        """
        x = 1
        def outer(a, /, b, *args, c, **kw):
            def inner(q):
                return q < 1
            return inner
        class K:
            y = 2
            def method(self, v):
                return v
        """
    )
    index = AstIndex.from_code(code)
    assert [u.fid for u in index.functions] == [("outer", 3), ("method", 2)]
    for node in index.order:
        if isinstance(node, ast.Compare):
            assert index.unit_of(node).fid == ("outer", 3)
        if isinstance(node, ast.Constant) and node.value == 2:
            assert index.unit_of(node) == MODULE_UNIT
    assert MODULE_UNIT.fid == ("", 0)


def test_async_function_is_a_unit() -> None:
    index = AstIndex.from_code("async def g(a, b):\n    return a < 1\n")
    assert [u.fid for u in index.functions] == [("g", 2)]


def test_site_order_functions_then_module_then_channel_then_rank() -> None:
    sites = read(
        """
        z = 0
        z += 1
        def f(a):
            b = a + 1
            c = 2 * a
            return b < 3
        def g(a):
            return a > 1
        """
    )
    got = [(s.unit.name, s.channel, s.rank) for s in sites]
    assert got == [
        ("f", "compare_dir", 0),
        ("f", "operand_order", 0),
        ("f", "operand_order", 1),
        ("g", "compare_dir", 0),
        ("", "aug_assign", 0),
    ]


def test_rank_per_function_and_channel() -> None:
    sites = read(
        """
        def f(a):
            return a < 1, a > 2, a + 1
        def g(a):
            return a < 1
        """
    )
    ranks = [(s.unit.name, s.channel, s.rank, s.value) for s in sites]
    assert ranks == [
        ("f", "compare_dir", 0, 1),
        ("f", "compare_dir", 1, 1),
        ("f", "operand_order", 0, 0),
        ("g", "compare_dir", 0, 1),
    ]


def test_site_carries_root_position() -> None:
    (site,) = read("def f(a):\n    if a < 1:\n        pass\n")
    assert (site.lineno, site.col_offset) == (2, 7)
    assert site.key == ("f", 1, "compare_dir", 0)


def test_overlap_lower_channel_wins_aug_vs_operand_order() -> None:
    # `x = x + 1` è sito 1; il suo BinOp interno non è sito 6.
    sites = read("def f(x):\n    x = x + 1\n    return x\n")
    assert [s.channel for s in sites] == ["aug_assign"]


def test_overlap_list_comp_owns_empty_list() -> None:
    sites = read(
        """
        def f(a):
            res = []
            for v in a:
                res.append(v)
            return res
        """
    )
    assert [s.channel for s in sites] == ["list_comp"]


def test_one_node_at_most_one_site() -> None:
    code = src(
        """
        def f(a, b):
            x = []
            for v in a:
                x.append(v + 1)
            y = x if a < b else None
            if a == None:
                t = 1 + a
            else:
                t = b
            n = n + 1
            return n is None, [] == a, dict()
        """
    )
    sites = find_sites_in_code(code)
    seen: set = set()
    for site in sites:
        assert not (site.owned & seen)
        seen |= site.owned


def test_count_by_channel_has_all_channels() -> None:
    counts = count_by_channel(read("def f(a):\n    return a < 1\n"))
    assert set(counts) == set(CHANNELS)
    assert counts["compare_dir"] == 1 and sum(counts.values()) == 1


def test_syntax_error_raises() -> None:
    with pytest.raises(SyntaxError):
        find_sites_in_code("def f(:\n")


def test_formatting_and_comments_do_not_matter() -> None:
    a = read(
        """
        def f(a):
            return a < 1 and (a + 1) > 2
        """
    )
    b = read(
        """
        def f(a):   # commento
            return (a<1
                    and ((a+1) > 2))  # altro
        """
    )
    assert [(s.key, s.value) for s in a] == [(s.key, s.value) for s in b]


def test_docstrings_contain_no_sites() -> None:
    assert read('def f(a):\n    """a < 1 and x = x + 1"""\n    return a\n') == []


DUP_FIDS = src(
    """
    class A:
        def run(self, v):
            return v < 1
    class B:
        def run(self, v):
            return v < 2
        def other(self):
            return self.x > 1
    def run(a, b):
        return a < 3
    """
)


def test_duplicate_fids_share_keys_and_get_dup_index() -> None:
    index = AstIndex.from_code(DUP_FIDS)
    assert [(u.fid, u.dup_index) for u in index.functions] == [
        (("run", 2), 0),
        (("run", 2), 1),
        (("other", 1), 0),
        (("run", 2), 2),
    ]
    assert index.n_duplicate_fids == 1
    sites = find_sites_in_code(DUP_FIDS)
    runs = [s for s in sites if s.unit.name == "run"]
    assert [s.key for s in runs] == [("run", 2, "compare_dir", 0)] * 3
    assert [s.dup_index for s in runs] == [0, 1, 2]
    assert MODULE_UNIT.dup_index == 0


def test_dup_index_does_not_enter_key() -> None:
    a = find_sites_in_code("def f(a):\n    return a < 1\n")
    b = find_sites_in_code("def f(a):\n    return a\ndef f(a):\n    return a < 1\n")
    assert a[0].key == b[0].key and (a[0].dup_index, b[0].dup_index) == (0, 1)
