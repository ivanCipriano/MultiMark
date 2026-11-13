"""Lettura dei canali 9–14 (§3.3.1b [v1.2]), opzione ``channels`` e regole di non interferenza."""

from __future__ import annotations

import pytest

from multimark.channels import CHANNEL_SETS, CHANNELS, ReadOptions
from multimark.inventory import inventory_code
from tests.helpers import channel_values, keys_values, read

# ---------------------------------------------------------------------- 9. range_zero


@pytest.mark.parametrize(
    "expr,value", [("range(0, n)", 0), ("range(n)", 1), ("range(0, len(n))", 0)]
)
def test_range_zero_forms(expr: str, value: int) -> None:
    assert channel_values(f"def f(n):\n    return {expr}\n", "range_zero") == [value]


@pytest.mark.parametrize(
    "expr", ["range(1, n)", "range(0, n, 2)", "range(0.0, n)", "range(False, n)", "range(*n)",
             "range(n, stop=3)", "range()", "xrange(0, n)"],
)  # fmt: skip
def test_range_zero_excluded(expr: str) -> None:
    assert channel_values(f"def f(n):\n    return {expr}\n", "range_zero") == []


def test_range_zero_rebound() -> None:
    code = "range = lambda *a: a\ndef f(n):\n    return range(0, n)\n"
    assert channel_values(code, "range_zero") == []
    assert channel_values(code, "range_zero", guards=False) == [0]


# ---------------------------------------------------------------------- 10. slice_lower


@pytest.mark.parametrize(
    "expr,value", [("a[0:n]", 0), ("a[0:]", 0), ("a[:n]", 1), ("a[:]", 1), ("a[0:len(a)]", 0)]
)
def test_slice_lower_forms(expr: str, value: int) -> None:
    assert channel_values(f"def f(a, n):\n    return {expr}\n", "slice_lower") == [value]


@pytest.mark.parametrize("expr", ["a[1:n]", "a[i:]", "a[0:n:2]", "a[::2]", "a[0]", "a[0:n, 1]"])
def test_slice_lower_excluded(expr: str) -> None:
    assert channel_values(f"def f(a, n, i):\n    return {expr}\n", "slice_lower") == []


# ---------------------------------------------------------------------- 11. else_return

ER0 = "def f(c, x):\n    if c:\n        return 1\n    else:\n        x = 2\n        return x\n"
ER1 = "def f(c, x):\n    if c:\n        return 1\n    x = 2\n    return x\n"


def test_else_return_forms() -> None:
    assert channel_values(ER0, "else_return") == [0]
    assert channel_values(ER1, "else_return") == [1]


@pytest.mark.parametrize("terminator", ["return", "raise ValueError()", "continue", "break"])
def test_else_return_terminators(terminator: str) -> None:
    code = f"def f(a):\n    for c in a:\n        if c:\n            {terminator}\n        g(c)\n"
    assert channel_values(code, "else_return") == [1]


@pytest.mark.parametrize(
    "code",
    [
        # il corpo non termina con un'uscita
        "def f(c):\n    if c:\n        g()\n    h()\n",
        # forma 1: ultima istruzione del blocco
        "def f(c):\n    if c:\n        return 1\n",
        # forma 0: elif / else: if
        "def f(c, d):\n    if c:\n        return 1\n    elif d:\n        return 2\n",
        # forma 0: non è l'ultima istruzione del blocco (non interferenza)
        "def f(c):\n    if c:\n        return 1\n    else:\n        g()\n    h()\n",
        # istruzioni spostate = una sola assegnazione con IfExp (non interferenza con ternary)
        "def f(c, d):\n    if c:\n        return 1\n    y = 1 if d else 2\n",
        "def f(c, d):\n    if c:\n        return 1\n    else:\n        y = 1 if d else 2\n",
        # l'if stesso è un elif
        "def f(c, d):\n    if d:\n        g()\n"
        "    elif c:\n        return 1\n    else:\n        h()\n",
    ],
)
def test_else_return_excluded(code: str) -> None:
    assert channel_values(code, "else_return") == []


def test_else_return_next_statement_is_if() -> None:
    # il primo if è seguito da un If: non è un sito; il secondo (seguito da return 3) sì
    code = "def f(c, d):\n    if c:\n        return 1\n    if d:\n        return 2\n    return 3\n"
    sites = [s for s in read(code) if s.channel == "else_return"]
    assert [(s.lineno, s.value) for s in sites] == [(4, 1)]


def test_nested_if_inner_of_chain_is_excluded_outer_is_site() -> None:
    # l'if interno è l'unica istruzione di un if senza else: escluso; l'esterno è forma 0
    code = "def f(a, b, c):\n    if c:\n        if a and b:\n            g()\n"
    assert [(s.lineno, s.value) for s in read(code) if s.channel == "nested_if"] == [(2, 0)]
    # test con and e corpo fatto di un solo if: forma 0 dell'esterno
    code = "def f(a, b, c):\n    if a and b:\n        if c:\n            g()\n"
    assert [(s.lineno, s.value) for s in read(code) if s.channel == "nested_if"] == [(2, 0)]


def test_else_return_followed_by_another_if_after_assignment() -> None:
    code = "def f(c, d):\n    if c:\n        return 1\n    y = 2\n    if d:\n        return y\n"
    assert channel_values(code, "else_return") == [1]


# ---------------------------------------------------------------------- 12. nested_if

NI0 = "def f(a, b):\n    if a:\n        if b:\n            g()\n"
NI1 = "def f(a, b):\n    if a and b:\n        g()\n"


def test_nested_if_forms() -> None:
    assert channel_values(NI0, "nested_if") == [0]
    assert channel_values(NI1, "nested_if") == [1]
    assert channel_values("def f(a, b, c):\n    if a and b and c:\n        g()\n", "nested_if") == [
        1
    ]


@pytest.mark.parametrize(
    "code",
    [
        # tre if annidati: né l'esterno né il medio sono siti
        "def f(a, b, c):\n    if a:\n        if b:\n            if c:\n                g()\n",
        # else sull'esterno o sull'interno
        "def f(a, b):\n    if a:\n        if b:\n            g()\n    else:\n        h()\n",
        "def f(a, b):\n    if a:\n        if b:\n            g()\n        else:\n            h()\n",
        # corpo dell'esterno con più istruzioni
        "def f(a, b):\n    if a:\n        if b:\n            g()\n        h()\n",
        # forma 1 con or / con corpo fatto di un solo if
        "def f(a, b):\n    if a or b:\n        g()\n",
        # non interferenza con else_return: corpo che termina con return e istruzioni dopo
        "def f(a, b):\n    if a and b:\n        return 1\n    g()\n",
        "def f(a, b):\n    if a:\n        if b:\n            return 1\n    g()\n",
    ],
)
def test_nested_if_excluded(code: str) -> None:
    assert channel_values(code, "nested_if") == []


def test_nested_if_with_return_but_nothing_after_is_a_site() -> None:
    code = "def f(a, b):\n    if a and b:\n        return 1\n"
    assert channel_values(code, "nested_if") == [1]
    assert channel_values(code, "else_return") == []


def test_if_and_return_with_statements_after_is_else_return() -> None:
    code = "def f(a, b):\n    if a and b:\n        return 1\n    g()\n"
    assert channel_values(code, "else_return") == [1]


# ---------------------------------------------------------------------- 13. square


@pytest.mark.parametrize(
    "expr,value",
    [("x * x", 0), ("x ** 2", 1), ("o.v * o.v", 0), ("o.v ** 2", 1), ("y + x * x", 0),
     ("a / x ** 2", 1), ("-x ** 2", 1)],
)  # fmt: skip
def test_square_forms(expr: str, value: int) -> None:
    assert channel_values(f"def f(x, o, y, a):\n    return {expr}\n", "square") == [value]


@pytest.mark.parametrize(
    "expr",
    ["x * y", "x ** 3", "x ** 2.0", "x ** True", "a[0] * a[0]", "g(x) * g(x)", "2 * x * x",
     "a * x ** 2", "x * x * a", "(x + 1) * (x + 1)"],
)  # fmt: skip
def test_square_excluded(expr: str) -> None:
    assert channel_values(f"def f(x, y, a):\n    return {expr}\n", "square") == []


def test_square_excluded_when_it_would_make_aug_assign() -> None:
    assert channel_values("def f(x):\n    x = x * x\n", "square") == []
    assert channel_values("def f(x):\n    x = x ** 2\n", "square") == []
    assert channel_values("def f(x):\n    x = x ** 2\n", "aug_assign") == [0]
    assert channel_values("def f(x, y):\n    y = x * x\n", "square") == [0]


# ---------------------------------------------------------------------- 14. return_none


def test_return_none_forms() -> None:
    assert channel_values("def f():\n    return None\n", "return_none") == [0]
    assert channel_values("def f():\n    return\n", "return_none") == [1]
    assert channel_values("def f():\n    return 0\n", "return_none") == []
    assert channel_values("def f():\n    return (None)\n", "return_none") == [0]


# ---------------------------------------------------------------------- opzione channels


def test_channel_sets() -> None:
    assert CHANNEL_SETS["mcss8"] == CHANNELS[:8] and len(CHANNEL_SETS["extended"]) == 14
    assert CHANNELS[8:] == (
        "range_zero", "slice_lower", "else_return", "nested_if", "square", "return_none",
    )  # fmt: skip
    with pytest.raises(ValueError):
        ReadOptions(channels="all")
    with pytest.raises(NotImplementedError):
        ReadOptions(channels="extended+str")


def test_mcss8_reads_only_first_eight() -> None:
    code = "def f(n, a):\n    if a < 1:\n        return None\n    return range(0, n), a[0:n]\n"
    ext = {s.channel for s in read(code)}
    old = {s.channel for s in read(code, channels="mcss8")}
    assert old == {"compare_dir"}
    assert ext == {"compare_dir", "return_none", "range_zero", "slice_lower", "else_return"}


def test_inventory_channels_option() -> None:
    code = "def f(n):\n    return range(0, n)\n"
    assert inventory_code(code)["n_sites_range_zero"] == 1
    assert inventory_code(code, channels="mcss8")["n_sites_range_zero"] == 0


def test_fstring_interiors_are_never_sites() -> None:
    code = "def f(a, n):\n    return f'{a < 1} {range(0, n)} {a is None}'\n"
    assert read(code) == []


# ---------------------------------------------------------------------- non interferenza

# Coppie (forma 0, forma 1) che differiscono per un solo sito dei canali nuovi: stesse chiavi,
# un solo valore diverso (vale per costruzione dell'insieme dei siti; la scrittura in P1 lo
# verifica su tutte le 2^k combinazioni).
NEW_PAIRS = [
    ("def f(n):\n    return range(0, n + 1)\n", "def f(n):\n    return range(n + 1)\n"),
    ("def f(a, n):\n    return a[0:n]\n", "def f(a, n):\n    return a[:n]\n"),
    (ER0, ER1),
    (NI0, NI1),
    ("def f(x, y):\n    y = x * x\n", "def f(x, y):\n    y = x ** 2\n"),
    ("def f():\n    return None\n", "def f():\n    return\n"),
    # else_return con istruzioni spostate che contengono altri siti
    ("def f(c, a):\n    if c:\n        return None\n    else:\n        out = []\n"
     "        for v in a:\n            out.append(v)\n        return out\n",
     "def f(c, a):\n    if c:\n        return None\n    out = []\n"
     "    for v in a:\n        out.append(v)\n    return out\n"),
    # nested_if con test che contengono siti
    ("def f(a, b):\n    if a < 1:\n        if b is None:\n            g()\n",
     "def f(a, b):\n    if a < 1 and b is None:\n        g()\n"),
]  # fmt: skip


@pytest.mark.parametrize("form0,form1", NEW_PAIRS)
def test_new_channels_one_form_change_keeps_site_set(form0: str, form1: str) -> None:
    a, b = keys_values(form0), keys_values(form1)
    assert [k for k, _ in a] == [k for k, _ in b]
    assert len([k for (k, va), (_, vb) in zip(a, b) if va != vb]) == 1
