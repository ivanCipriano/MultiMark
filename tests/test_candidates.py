"""Inventario dei canali candidati (P0-bis): un frammento per pattern e forma, casi assenti,
aggregazione, stima e CLI."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from multimark.candidates import (
    COUNTERS,
    PATTERNS,
    PATTERNS_BY_NAME,
    added_sites,
    candidate_hits,
    count_candidates,
    estimate,
    estimate_counters,
    rank_patterns,
    sample_row,
    summarize_candidates,
)
from multimark.cli.candidates import main
from tests.helpers import src


def counts(code: str) -> dict:
    out = count_candidates(src(code))
    assert out is not None
    return out


# (frammento, contatore, occorrenze attese). Ogni pattern ha le sue forme e almeno un caso assente.
CASES = [
    # a. else superfluo dopo return (T16)
    ("def f(c):\n    if c:\n        return 1\n    else:\n        return 2\n", "else_return_f0", 1),
    ("def f(c):\n    if c:\n        return 1\n    return 2\n", "else_return_f1", 1),
    ("def f(c):\n    if c:\n        g()\n        return 1\n    return 2\n", "else_return_f1", 0),
    ("def f(c):\n    if c:\n        return 1\n    g()\n", "else_return_f1", 0),
    # b. range(len(a)) con a[i] / enumerate (T38)
    ("def f(a):\n    for i in range(len(a)):\n        print(a[i])\n", "range_len_f0", 1),
    ("def f(a, b):\n    for i in range(len(a)):\n        print(b[i])\n", "range_len_f0", 0),
    ("def f(a):\n    for i, x in enumerate(a):\n        print(x)\n", "range_len_f1", 1),
    ("def f(a):\n    for i, x in enumerate(a, start=1):\n        print(x)\n", "range_len_f1", 0),
    # c. x*x / x**2 (T7)
    ("def f(x):\n    return x * x\n", "square_f0", 1),
    ("def f(x):\n    return g(x) * g(x)\n", "square_f0", 0),
    ("def f(x):\n    return x ** 2\n", "square_f1", 1),
    ("def f(x):\n    return x ** 3\n", "square_f1", 0),
    # d. not a == b / a != b
    ("def f(a, b):\n    return not a == b\n", "not_eq_f0", 1),
    ("def f(a, b):\n    return a != b\n", "not_eq_f1", 1),
    ("def f(a, b):\n    return not a < b\n", "not_eq_f0", 0),
    # e. len(a) == 0, len(a) > 0 / a, not a in condizione
    ("def f(a):\n    return len(a) == 0, len(a) > 0\n", "len_test_f0", 2),
    ("def f(a):\n    return len(a) >= 0, len(a) == 1\n", "len_test_f0", 0),
    ("def f(a, b):\n    if not a and b.c:\n        pass\n", "len_test_f1", 2),
    ("def f(a):\n    return not a\n", "len_test_f1", 0),
    # f. a[0:n] / a[:n], a[i:len(a)] / a[i:] (T2)
    ("def f(a, n, i):\n    return a[0:n], a[i:len(a)]\n", "slice_bound_f0", 2),
    ("def f(a, n, i):\n    return a[:n], a[i:]\n", "slice_bound_f1", 2),
    ("def f(a, n, i):\n    return a[i:n], a[:], a[::2]\n", "slice_bound_f0", 0),
    ("def f(a, n, i):\n    return a[i:n], a[:], a[::2]\n", "slice_bound_f1", 0),
    # g. metodi di str (T39)
    ("def f(s):\n    return s.split(','), ','.join(s), s.strip()\n", "str_method_f0", 3),
    ("def f(s):\n    return str.split(s, ',')\n", "str_method_f1", 1),
    ("def f(s):\n    return str.split(s, ',')\n", "str_method_f0", 0),
    ("def f(s):\n    return s.encode()\n", "str_method_f0", 0),
    # h. if c: return True else: return False / return bool(c) / return c
    ("def f(c):\n    if c:\n        return True\n    else:\n        return False\n",
     "bool_return_f0", 1),
    ("def f(c):\n    if c:\n        return False\n    else:\n        return True\n",
     "bool_return_f0", 0),
    ("def f(c):\n    return bool(c)\n", "bool_return_f1", 1),
    ("def f(a, b):\n    return a < b\n", "bool_return_f2", 1),
    ("def f(a, b):\n    return a\n", "bool_return_f2", 0),
    # i. elif / else: if (T9): stesso ast, un solo contatore
    ("def f(a, b):\n    if a:\n        pass\n    elif b:\n        pass\n", "elif_f0", 1),
    ("def f(a, b):\n    if a:\n        pass\n    else:\n        if b:\n            pass\n",
     "elif_f0", 1),
    ("def f(a, b):\n    if a:\n        pass\n    else:\n        g()\n", "elif_f0", 0),
    # j. if annidati / if a and b (T17)
    ("def f(a, b):\n    if a:\n        if b:\n            g()\n", "nested_if_f0", 1),
    ("def f(a, b):\n    if a:\n        if b:\n            g()\n        else:\n            h()\n",
     "nested_if_f0", 0),
    ("def f(a, b):\n    if a and b:\n        g()\n", "nested_if_f1", 1),
    ("def f(a, b):\n    if a and b:\n        g()\n    else:\n        h()\n", "nested_if_f1", 0),
    # k. range(0, n) / range(n)
    ("def f(n):\n    return range(0, n)\n", "range_zero_f0", 1),
    ("def f(n):\n    return range(n)\n", "range_zero_f1", 1),
    ("def f(n):\n    return range(1, n)\n", "range_zero_f0", 0),
    # l. a == b or a == c / a in (b, c) (T6)
    ("def f(a, b, c):\n    return a == b or a == c\n", "or_eq_f0", 1),
    ("def f(a, b, c):\n    return a == b or c == b\n", "or_eq_f0", 0),
    ("def f(a, b, c):\n    return a in (b, c), a in [b, c]\n", "or_eq_f1", 2),
    ("def f(a, b):\n    return a in b\n", "or_eq_f1", 0),
    # m. [x for x in a] / list(a) (T31)
    ("def f(a):\n    return [x for x in a]\n", "identity_comp_f0", 1),
    ("def f(a):\n    return [x + 1 for x in a], [x for x in a if x]\n", "identity_comp_f0", 0),
    ("def f(a):\n    return list(a)\n", "identity_comp_f1", 1),
    ("def f(a):\n    return list(), list(a, b)\n", "identity_comp_f1", 0),
    # n. sorted(a)[::-1] / sorted(a, reverse=True)
    ("def f(a):\n    return sorted(a)[::-1]\n", "sorted_rev_f0", 1),
    ("def f(a):\n    return sorted(a)[::2], a[::-1]\n", "sorted_rev_f0", 0),
    ("def f(a):\n    return sorted(a, reverse=True)\n", "sorted_rev_f1", 1),
    ("def f(a):\n    return sorted(a, reverse=False)\n", "sorted_rev_f1", 0),
    # o. f-string / format / concatenazione con str()
    ("def f(x):\n    return f'{x:>{4}}'\n", "str_build_f0", 1),  # la spec annidata non conta
    ("def f(x):\n    return '{}'.format(x)\n", "str_build_f1", 1),
    ("def f(x):\n    return 'a' + str(x) + 'b'\n", "str_build_f2", 1),
    ("def f(x):\n    return 'a' + x\n", "str_build_f2", 0),
    # p. a == True ... / a, not a (= e.f1)
    ("def f(a):\n    return a == True, a == False, a is True, a is False\n", "bool_cmp_f0", 4),
    ("def f(a):\n    return a == 1, a is None\n", "bool_cmp_f0", 0),
    ("def f(a):\n    while a:\n        pass\n", "bool_cmp_f1", 1),
    # q. while True con un solo if ...: break in testa / while not cond
    ("def f(c):\n    while True:\n        if c():\n            break\n        g()\n",
     "while_break_f0", 1),
    ("def f(c):\n    while True:\n        if c():\n            break\n        if d():\n"
     "            break\n", "while_break_f0", 0),
    ("def f(c):\n    while True:\n        g()\n        if c():\n            break\n",
     "while_break_f0", 0),
    ("def f(c):\n    while True:\n        if c():\n            break\n        for x in y:\n"
     "            break\n", "while_break_f0", 1),  # il break del for annidato non conta
    ("def f(c):\n    while not c():\n        g()\n", "while_break_f1", 1),
    ("def f(c):\n    while c():\n        g()\n", "while_break_f1", 0),
    # r. costante ** costante
    ("def f():\n    return 10 ** 3\n", "const_pow_f0", 1),
    ("def f(x):\n    return 10 ** x, 1000, 1e3\n", "const_pow_f0", 0),
    # s. d.get(k, None) / d.get(k)
    ("def f(d, k):\n    return d.get(k, None)\n", "get_none_f0", 1),
    ("def f(d, k):\n    return d.get(k)\n", "get_none_f1", 1),
    ("def f(d, k):\n    return d.get(k, 0)\n", "get_none_f0", 0),
    # t. return None / return
    ("def f():\n    return None\n", "return_none_f0", 1),
    ("def f():\n    return\n", "return_none_f1", 1),
    ("def f():\n    return 0\n", "return_none_f0", 0),
    # u. x = x + 1 / x += 1 (per confronto)
    ("def f(x):\n    x = x + 1\n    x -= 2\n", "aug_inc_f0", 1),
    ("def f(x):\n    x = x + 1\n    x -= 2\n", "aug_inc_f1", 1),
    ("def f(x, y):\n    x += y\n", "aug_inc_f1", 0),
    # v. max(a, b) / a if a > b else b
    ("def f(a, b):\n    return max(a, b)\n", "max_ternary_f0", 1),
    ("def f(a, b):\n    return max(a), max(a, b, c)\n", "max_ternary_f0", 0),
    ("def f(a, b):\n    return a if a > b else b, b if a < b else a\n", "max_ternary_f1", 2),
    ("def f(a, b):\n    return a if a < b else b\n", "max_ternary_f1", 0),
    # w. s == "" / not s / len(s) == 0
    ("def f(s):\n    return s == '', '' == s\n", "empty_str_f0", 2),
    ("def f(s):\n    return s == ' '\n", "empty_str_f0", 0),
    ("def f(s):\n    if not s:\n        pass\n", "empty_str_f1", 1),
    ("def f(s):\n    return len(s) == 0, len(s) > 0\n", "empty_str_f2", 1),
]  # fmt: skip


@pytest.mark.parametrize("code,counter,expected", CASES)
def test_pattern_counts(code: str, counter: str, expected: int) -> None:
    assert counts(code)[f"cand_{counter}"] == expected


def test_every_pattern_and_form_is_tested() -> None:
    tested = {f"cand_{c}" for _, c, n in CASES if n > 0}
    absent = {f"cand_{c}" for _, c, n in CASES if n == 0}
    assert tested == set(COUNTERS)
    assert {p.name for p in PATTERNS} == {c[5:].rsplit("_f", 1)[0] for c in absent}


def test_letters_and_names_are_unique() -> None:
    assert [p.letter for p in PATTERNS] == list("abcdefghijklmnopqrstuvw")
    assert len(PATTERNS_BY_NAME) == len(PATTERNS)


def test_counting_does_not_change_code() -> None:
    code = src("def f(a):\n    return a[0:2] if not a else a[:2]\n")
    before = code
    count_candidates(code)
    assert code == before


def test_formatting_and_comments_do_not_matter() -> None:
    a = counts("def f(a):\n    return a[0:2], len(a) == 0\n")
    b = counts("def f(a):   # c\n    return (a[0 : 2],\n            len( a )==0)\n")
    assert a == b


def test_syntax_error() -> None:
    assert count_candidates("def f(:\n") is None
    assert sample_row("def f(:\n") == {"parse_ok": False}


def test_hits_have_positions() -> None:
    hits = candidate_hits("def f(n):\n    return range(0, n)\n")
    assert ("cand_range_zero_f0", 2, 11, "range(0, n)") in hits


def test_estimate_counters() -> None:
    assert estimate_counters(PATTERNS_BY_NAME["aug_inc"]) == ()
    assert estimate_counters(PATTERNS_BY_NAME["aug_inc"], all_forms=True) == ()
    assert estimate_counters(PATTERNS_BY_NAME["elif"], all_forms=True) == ()
    assert estimate_counters(PATTERNS_BY_NAME["len_test"]) == ("cand_len_test_f0",)
    assert estimate_counters(PATTERNS_BY_NAME["len_test"], all_forms=True) == (
        "cand_len_test_f0",
        "cand_len_test_f1",
    )


def _rows() -> list:
    return [
        sample_row("def f(a):\n    return a[0:1], a[0:2], range(0, 3)\n"),
        sample_row("def f(a):\n    return range(0, 3)\n"),
        sample_row("def f(:\n"),
    ]


def test_summary() -> None:
    s = summarize_candidates(_rows())
    assert (s["n_samples"], s["n_parsed"]) == (3, 2)
    st = s["counters"]["cand_range_zero_f0"]
    assert (st["total"], st["mean"], st["frac_ge_1"]) == (2, 1.0, 1.0)
    assert s["counters"]["cand_slice_bound_f0"]["frac_ge_1"] == 0.5


def test_ranking_and_estimate() -> None:
    rows = _rows()
    ranking = rank_patterns(rows)
    assert ranking[:2] == [("slice_bound", 2), ("range_zero", 2)]  # pari merito: lettera (f < k)
    assert all(total == 0 for _, total in ranking[2:])
    assert "len_test" in [n for n, _ in ranking] and "elif" not in [n for n, _ in ranking]
    assert added_sites(rows[0], ["range_zero", "slice_bound"]) == 3
    est = estimate(rows, ranking, ks=(1, 2), thresholds=(1, 3))
    assert est[0]["frac_ge_1"] == 0.0  # nessun sito attuale (a, f non sono siti dei nomi)
    assert est[1] == {"patterns": ["slice_bound"], "frac_ge_1": 0.5, "frac_ge_3": 0.0}
    assert est[2] == {"patterns": ["slice_bound", "range_zero"], "frac_ge_1": 1.0, "frac_ge_3": 0.5}
    assert math.isnan(estimate([], [], ks=(), thresholds=(8,))[0]["frac_ge_8"])


def test_cli(tmp_path: Path) -> None:
    paths = {}
    for label, code in (("canonical", "def f(n):\n    return range(0, n)\n"),
                        ("qwen", "def f(a):\n    return a[:2]\n")):  # fmt: skip
        p = tmp_path / f"{label}.jsonl"
        p.write_text(json.dumps({"id": label, "code": code}) + "\n", encoding="utf-8")
        paths[label] = p
    summary, js, out = tmp_path / "s.txt", tmp_path / "s.json", tmp_path / "rows.csv"
    rc = main(
        ["--input", f"canonical={paths['canonical']}", "--input", f"qwen={paths['qwen']}",
         "--summary", str(summary), "--summary-json", str(js), "--output", str(out),
         "--id-field", "id"]
    )  # fmt: skip
    assert rc == 0
    text = summary.read_text(encoding="utf-8")
    assert "== group canonical" in text and "== group qwen" in text
    assert "ranking prudent" in text and "estimate all_forms, group qwen" in text
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["groups"]["canonical"]["counters"]["cand_range_zero_f0"]["total"] == 1
    assert set(data["estimate"]["prudent"]["groups"]) == {"canonical", "qwen"}
    assert out.read_text(encoding="utf-8").splitlines()[0].startswith("group,id,parse_ok")


def test_cli_bad_input(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(["--input", "no-label"])
    p = tmp_path / "a.jsonl"
    p.write_text('{"code": "x = 1\\n"}\n', encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--input", f"a={p}", "--estimate-groups", "b"])
