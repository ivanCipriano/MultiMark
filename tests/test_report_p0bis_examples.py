"""Le occorrenze di ``docs/reports/P0bis_candidati.md`` (tre esempi).

Se un test fallisce, il riconoscimento dei candidati è cambiato: il report va rigenerato e riletto.
"""

from __future__ import annotations

from multimark.candidates import candidate_hits
from multimark.inventory import inventory_code

# Codice identico a quello del report.
A = '''from typing import List, Optional


def longest(strings: List[str]) -> Optional[str]:
    """ Out of list of strings, return the longest one. Return the first one in case of multiple
    strings of the same length. Return None in case the input list is empty.
    >>> longest([])

    >>> longest(['a', 'b', 'c'])
    'a'
    >>> longest(['a', 'bb', 'ccc'])
    'ccc'
    """
    if not strings:
        return None

    maxlen = max(len(x) for x in strings)
    for s in strings:
        if len(s) == maxlen:
            return s
'''

B = """def summarize(records, key=None):
    if len(records) == 0:
        return None
    names = [r for r in records]
    result = []
    for i in range(len(names)):
        name = names[i].strip()
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
    return sorted(result)[::-1], label
"""

C = """def check(a, b, x, items):
    if a:
        return True
    else:
        return False


def near_misses(a, b, x, items):
    if a > 0:
        pass
    elif b:
        pass
    scale = 1e3
    cube = x ** 3
    rev = items[::-1]
    top = max(items)
    x += b
    while True:
        x = x - 1
        if x < 0:
            break
    either = a == 1 or b == 1
    return a, scale, cube, rev, top, either
"""


def hits(code: str) -> list:
    return [(c[5:], line, col) for c, line, col, _ in candidate_hits(code)]


def test_example_1() -> None:
    assert hits(A) == [
        ("len_test_f1", 14, 7),
        ("bool_cmp_f1", 14, 7),
        ("empty_str_f1", 14, 7),
        ("return_none_f0", 15, 8),
    ]
    assert inventory_code(A)["n_sites_total"] == 2


def test_example_2() -> None:
    assert hits(B) == [
        ("len_test_f0", 2, 7),
        ("empty_str_f2", 2, 7),
        ("return_none_f0", 3, 8),
        ("identity_comp_f0", 4, 12),
        ("range_len_f0", 6, 4),
        ("range_zero_f1", 6, 13),
        ("str_method_f0", 7, 15),
        ("or_eq_f0", 8, 11),
        ("empty_str_f0", 8, 11),
        ("slice_bound_f0", 12, 30),
        ("str_method_f0", 14, 26),
        ("range_len_f1", 16, 4),
        ("get_none_f0", 17, 17),
        ("str_build_f2", 18, 12),
        ("sorted_rev_f0", 19, 11),
    ]
    assert inventory_code(B)["n_sites_total"] == 12


def test_example_3() -> None:
    assert hits(C) == [
        ("else_return_f0", 2, 4),
        ("bool_return_f0", 2, 4),
        ("len_test_f1", 2, 7),
        ("bool_cmp_f1", 2, 7),
        ("empty_str_f1", 2, 7),
        ("elif_f0", 9, 4),
        ("len_test_f1", 11, 9),
        ("bool_cmp_f1", 11, 9),
        ("empty_str_f1", 11, 9),
        ("aug_inc_f0", 19, 8),
    ]
    assert inventory_code(C)["n_sites_total"] == 10
