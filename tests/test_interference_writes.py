"""Non interferenza (§3.3.2 punto 3, criteri di accettazione di P1 [v1.2]).

Frammenti che combinano canali vecchi e nuovi sugli stessi nodi: per **tutte** le ``2^k``
scritture possibili dei ``k`` siti, l'insieme dei siti ``(fid, canale, rango)`` resta quello di
partenza e ogni sito rilegge il valore scritto.
"""

from __future__ import annotations

import itertools
import textwrap

import pytest

from multimark._astindex import AstIndex
from multimark.channels import ReadOptions
from multimark.rewrite import WriteRequest, write_structural
from multimark.sites import find_sites

COMBOS = {
    # if a and b: return X + istruzioni dopo (else_return vince, nested_if escluso)
    "and_return_then_statements": """
        def f(a, b, x):
            if a and b:
                return x[0:2]
            y = x + 1
            return None
        """,
    # L = list() + ciclo con append (né empty_coll né list_comp) e L = [] + ciclo (list_comp)
    "list_call_and_list_comp": """
        def f(a):
            out = list()
            for v in a:
                out.append(v)
            res = []
            for w in a:
                res.append(w * 2)
            return out, res
        """,
    # x = x + 1 dentro un for su range(0, x + 1)
    "aug_inside_range": """
        def f(x):
            for i in range(0, x + 1):
                x = x + 1
            return x
        """,
    # ternario come istruzione dopo un if che termina con return (regola _ifish: non è un sito
    # else_return in nessuna delle due forme del ternario)
    "ternary_after_else_return": """
        def f(c, n):
            if c is None:
                return 0
            if n:
                y = n
            else:
                y = 0
            return y
        """,
    # ternario come istruzione dopo un else_return seguito da altro (il sito resta)
    "ternary_after_else_return_with_more": """
        def f(c, n):
            if c is None:
                return 0
            z = n + 1
            if n:
                y = n
            else:
                y = 0
            return y, z
        """,
    # else_return in forma 0 con un list_comp e un empty_coll nell'else
    "else_return_with_comprehension": """
        def f(c, a):
            if c:
                return None
            else:
                out = [v * 2 for v in a]
                extra = {}
                return out, extra
        """,
    # nested_if con siti nei test e nel corpo
    "nested_if_with_compare": """
        def f(a, b, x):
            if a < 1:
                if b is None:
                    x = x - 1
            return x
        """,
    # nested_if con corpo ternario (regola _ifish)
    "nested_if_with_ternary_body": """
        def f(a, b, n):
            if a and b:
                if n:
                    y = n
                else:
                    y = 0
            return None
        """,
    # square, operand_order e slice nello stesso calcolo
    "square_operand_slice": """
        def f(x, data):
            y = x * x + 1
            z = data[0:x ** 2]
            return y, z, 2 * x
        """,
    # ternario con rami vuoti e confronto con None nel test
    "ternary_branches_empty_coll": """
        def f(a):
            if a is None:
                v = []
            else:
                v = {}
            return v
        """,
}


@pytest.mark.parametrize("name", list(COMBOS))
def test_all_writes_keep_site_set(name: str) -> None:
    code = textwrap.dedent(COMBOS[name]).lstrip("\n")
    index = AstIndex.from_code(code)
    sites = find_sites(index, ReadOptions())
    keys = [s.key for s in sites]
    assert 2 <= len(sites) <= 9, (name, [s.key for s in sites])
    for bits in itertools.product((0, 1), repeat=len(sites)):
        requests = [WriteRequest(s, b) for s, b in zip(sites, bits)]
        new, unwritable = write_structural(code, index, requests)
        assert not unwritable, (name, bits)
        after = find_sites(AstIndex.from_code(new), ReadOptions())
        assert [s.key for s in after] == keys, (name, bits, new)
        assert [s.value for s in after] == list(bits), (name, bits, new)


def test_expected_channels_in_combos() -> None:
    def channels(name: str) -> set[str]:
        code = textwrap.dedent(COMBOS[name]).lstrip("\n")
        return {s.channel for s in find_sites(AstIndex.from_code(code), ReadOptions())}

    assert "else_return" in channels("and_return_then_statements")
    assert "nested_if" not in channels("and_return_then_statements")
    assert channels("list_call_and_list_comp") >= {"list_comp"}
    assert "empty_coll" not in channels("list_call_and_list_comp")
    assert {"aug_assign", "range_zero"} <= channels("aug_inside_range")
    assert "else_return" not in channels("ternary_after_else_return")
    assert {"else_return", "ternary"} <= channels("ternary_after_else_return_with_more")
    assert {"ternary", "empty_coll"} <= channels("ternary_branches_empty_coll")
    assert {"nested_if", "compare_dir", "none_check", "aug_assign"} <= channels(
        "nested_if_with_compare"
    )
    assert "nested_if" not in channels("nested_if_with_ternary_body")
