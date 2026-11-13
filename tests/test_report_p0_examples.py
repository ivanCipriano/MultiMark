"""Le affermazioni di ``docs/reports/P0_esempi.md`` (siti e non siti dei tre esempi).

Se uno di questi test fallisce, il comportamento del riconoscimento è cambiato: il report va
rigenerato e riletto.
"""

from __future__ import annotations

import ast

from multimark._astindex import AstIndex
from multimark.channels import ReadOptions
from multimark.inventory import inventory_code
from multimark.names import name_sites
from multimark.sites import find_sites, find_sites_in_code, loop_form_targets

# Codice identico a quello del report (righe numerate lì).
A = '''from typing import List


def below_zero(operations: List[int]) -> bool:
    """ You're given a list of deposit and withdrawal operations on a bank account that starts with
    zero balance. Your task is to detect if at any point the balance of account falls below zero, and
    at that point function should return True. Otherwise it should return False.
    >>> below_zero([1, 2, 3])
    False
    >>> below_zero([1, 2, -4, 5])
    True
    """
    balance = 0

    for op in operations:
        balance += op
        if balance < 0:
            return True

    return False
'''

B = """class Stats:
    def __init__(self, values=None):
        if values is None:
            values = []
        self.values = values
        self.total = 0

    def add(self, value):
        self.values.append(value)
        self.total = self.total + value
        return self


def mean(values):
    if len(values) == 0:
        return None
    return sum(values) / len(values)


def summary(values, digits=2):
    stats = Stats(values)
    scaled = []
    for item in values:
        scaled.append(item * 2)
    avg = mean(values)
    label = "empty" if avg is None else "ok"
    spread = max(values) - min(values) if values else 0
    count = len(values)
    count -= 1
    ratio = 100 * count
    return {"label": label, "avg": round(avg, digits), "ratio": ratio, "spread": spread}
"""

C = """def tricky(x, items, flag):
    x = x * 2
    x = 1 + x
    x = x + flag
    if flag:
        res = x + 1
    elif items:
        res = 0
    else:
        res = 1
    out = []
    for val in items:
        out.append(val)
    print(val)
    pick = x if flag else (1 if items else 2)
    both = 1 + 2
    return 0 < x < 10, flag == True, len(items) < len(out), pick, both, res


def shadow(list):
    return list()
"""


def site_texts(code: str, guards: bool = True) -> set:
    return {
        (s.channel, (ast.get_source_segment(code, s.node) or "").split(chr(10))[0].strip())
        for s in find_sites_in_code(code, ReadOptions(guards=guards))
    }


def name_set(code: str, include_params: bool = False) -> set:
    index = AstIndex.from_code(code)
    targets = loop_form_targets(find_sites(index), index)
    return {
        n.name
        for n in name_sites(index, include_params=include_params, excluded_binding_ids=targets)
    }


def test_example_1_short_function() -> None:
    assert site_texts(A) == {("compare_dir", "balance < 0")}
    assert [s.value for s in find_sites_in_code(A)] == [1]
    assert name_set(A) == {"balance", "op"}
    assert name_set(A, include_params=True) == {"operations", "balance", "op"}
    assert ("aug_assign", "balance += op") in site_texts(A, guards=False)
    row = inventory_code(A)
    assert (row["n_sites_total"], row["n_bits_v1"], row["loc"]) == (3, 5, 8)


def test_example_2_functions_and_class() -> None:
    sites = site_texts(B)
    assert sites == {
        ("empty_coll", "[]"),
        ("none_check", "values is None"),
        ("equality_dir", "len(values) == 0"),
        ("aug_assign", "count -= 1"),
        ("list_comp", "scaled = []"),
        ("ternary", 'label = "empty" if avg is None else "ok"'),
        ("operand_order", "item * 2"),
        ("operand_order", "100 * count"),
        ("none_check", "avg is None"),
    }
    # il [] di `scaled = []` appartiene al sito list_comp: un solo empty_coll (riga 4)
    empties = [s for s in find_sites_in_code(B) if s.channel == "empty_coll"]
    assert [s.lineno for s in empties] == [4]
    assert [u.fid for u in AstIndex.from_code(B).functions] == [
        ("__init__", 2), ("add", 2), ("mean", 1), ("summary", 2),
    ]  # fmt: skip
    assert name_set(B) == {"stats", "scaled", "avg", "label", "spread", "count", "ratio"}
    assert "values" not in name_set(B, include_params=True)
    assert {"value", "digits"} <= name_set(B, include_params=True)
    assert any(t.startswith("spread") for _, t in site_texts(B, guards=False))
    assert inventory_code(B, canonical="paper", include_params=True)["n_bits_v1"] == 27


def test_example_3_near_sites() -> None:
    assert site_texts(C) == {
        ("operand_order", "x * 2"),
        ("operand_order", "x + 1"),
        ("empty_coll", "[]"),
    }
    assert name_set(C) == {"res", "out", "val", "pick", "both"}
    assert name_set(C, include_params=True) == {
        "items", "flag", "res", "out", "val", "pick", "both", "list",
    }  # fmt: skip
    assert site_texts(C, guards=False) == {
        ("aug_assign", "x = x * 2"),
        ("aug_assign", "x = x + flag"),
        ("list_comp", "out = []"),
        ("operand_order", "x + 1"),
        ("empty_coll", "list()"),
    }
