"""Riconoscimento dei canali (§3.3.1): presente/assente, forma 0/forma 1, casi esclusi,
modalità ``paper``, ``guards=False``, non interferenza fra le due forme (§3.3.2 punto 3)."""

from __future__ import annotations

import pytest

from multimark.channels import ReadOptions
from tests.helpers import channel_values, keys_values, read

# ---------------------------------------------------------------------- 1. aug_assign


@pytest.mark.parametrize(
    "stmt,value",
    [
        ("x = x + 1", 0),
        ("x = x - 2.5", 0),
        ("x += 1", 1),
        ("x -= 3", 1),
        ("x = x / y", 0),
        ("x //= y", 1),
        ("x = x % (y + 1)", 0),
        ("x **= 2", 1),
    ],
)
def test_aug_assign_forms(stmt: str, value: int) -> None:
    assert channel_values(f"def f(x, y):\n    {stmt}\n", "aug_assign") == [value]


@pytest.mark.parametrize(
    "stmt",
    [
        "x = x * 2",  # mai *
        "x *= 2",
        "x |= y",
        "x = x & y",
        "x ^= 1",
        "x <<= 1",
        "x = x @ y",
        "x = x + y",  # + solo con costante numerica
        "x += y",
        "x = x + True",  # bool non è numerico
        "x = x / g(y)",  # e non puro
        "x = y + 1",  # bersaglio diverso
        "x.a = x.a + 1",  # bersaglio non Name
        "x = 1 + x",  # x non a sinistra (è sito 6? no: vedi test di non interferenza)
        "x = y = x + 1",  # più bersagli
    ],
)
def test_aug_assign_excluded(stmt: str) -> None:
    assert channel_values(f"def f(x, y):\n    {stmt}\n", "aug_assign") == []


# ---------------------------------------------------- 2, 3. compare_dir, equality_dir


@pytest.mark.parametrize(
    "expr,value",
    [
        ("1 < a", 0),  # Constant(0) a sinistra di Name(1)
        ("a > 1", 1),
        ("a <= a.b", 0),  # Name(1) < Attribute(2)
        ("a[0] >= a.b", 1),  # Subscript(3) > Attribute(2)
        ("len(a) < a", 1),  # Call(4) > Name(1), uno solo non puro
        ("-1 < a", 1),  # UnaryOp(5)
        ("a < a + 1", 0),
        ("(a, b) < a", 1),  # Tuple = altro(6)
    ],
)
def test_compare_dir_forms(expr: str, value: int) -> None:
    assert channel_values(f"def f(a, b):\n    return {expr}\n", "compare_dir") == [value]


@pytest.mark.parametrize(
    "expr",
    [
        "a < b",  # stesso kind
        "a.x < b.y",
        "1 < 2",
        "a < b < 3",  # due operatori
        "len(a) < len(b)",  # due non puri (e stesso kind)
        "len(a) < g(b) + 1",  # due non puri
        "(a < b) < 1",  # operando Compare
        "a == 1",  # canale 3, non 2
        "a in b",
    ],
)
def test_compare_dir_excluded(expr: str) -> None:
    assert channel_values(f"def f(a, b):\n    return {expr}\n", "compare_dir") == []


@pytest.mark.parametrize(
    "expr,value",
    [("a == 1", 1), ("1 != a", 0), ("a.b == a", 1), ("a[0] != len(a)", 0)],
)
def test_equality_dir_forms(expr: str, value: int) -> None:
    assert channel_values(f"def f(a):\n    return {expr}\n", "equality_dir") == [value]


@pytest.mark.parametrize(
    "expr",
    ["a == None", "None != a", "a == True", "False == a", "a == a", "a == b == 1", "a in b"],
)
def test_equality_dir_excluded(expr: str) -> None:
    assert channel_values(f"def f(a, b):\n    return {expr}\n", "equality_dir") == []


def test_compare_paper_mode_breaks_ties_by_text() -> None:
    code = "def f(alpha, beta):\n    return alpha < beta, beta == alpha, alpha < alpha\n"
    assert channel_values(code, "compare_dir") == []
    assert channel_values(code, "compare_dir", canonical="paper") == [0]
    assert channel_values(code, "equality_dir", canonical="paper") == [1]


def test_compare_paper_mode_depends_on_names() -> None:
    a = channel_values(
        "def f(alpha, beta):\n    return alpha < beta\n", "compare_dir", canonical="paper"
    )
    b = channel_values(
        "def f(zeta, beta):\n    return zeta < beta\n", "compare_dir", canonical="paper"
    )
    assert a == [0] and b == [1]


def test_compare_kind_mode_independent_of_names() -> None:
    a = channel_values("def f(alpha):\n    return alpha < 3\n", "compare_dir")
    b = channel_values("def f(zeta):\n    return zeta < 3\n", "compare_dir")
    assert a == b == [1]


def test_bad_canonical_mode() -> None:
    with pytest.raises(ValueError):
        ReadOptions(canonical="nope")


# ---------------------------------------------------------------------- 4. list_comp

LOOP = """
def f(items):
    out = []
    for item in items:
        out.append(item * 2)
    return out
"""
COMP = """
def f(items):
    out = [item * 2 for item in items]
    return out
"""


def test_list_comp_forms() -> None:
    assert channel_values(LOOP, "list_comp") == [0]
    assert channel_values(COMP, "list_comp") == [1]


@pytest.mark.parametrize(
    "code",
    [
        # due istruzioni nel corpo
        "def f(a):\n    out = []\n    for v in a:\n        out.append(v)\n        g(v)\n",
        # else del for
        "def f(a):\n    out = []\n    for v in a:\n        out.append(v)\n    else:\n        g()\n",
        # istruzioni non consecutive
        "def f(a):\n    out = []\n    k = 1\n    for v in a:\n        out.append(v)\n",
        # x letto dopo il ciclo
        "def f(a):\n    out = []\n    for v in a:\n        out.append(v)\n    return out, v\n",
        # L in expr
        "def f(a):\n    out = []\n    for v in a:\n        out.append(len(out))\n",
        # x in it
        "def f(v):\n    out = []\n    for v in v:\n        out.append(v)\n",
        # append con due argomenti / con keyword / starred
        "def f(a):\n    out = []\n    for v in a:\n        out.append(*v)\n",
        # bersaglio tupla
        "def f(a):\n    out = []\n    for v, w in a:\n        out.append(v)\n",
        # altra lista
        "def f(a, o):\n    out = []\n    for v in a:\n        o.append(v)\n",
        # comprehension con if / con due clausole / con bersaglio tupla
        "def f(a):\n    out = [v for v in a if v]\n",
        "def f(a):\n    out = [v for v in a for w in v]\n",
        "def f(a):\n    out = [v for v, w in a]\n",
        # comprehension con x letto dopo
        "def f(a):\n    out = [v for v in a]\n    return v\n",
        # async for
        "async def f(a):\n    out = []\n    async for v in a:\n        out.append(v)\n",
        # L = list() non è la forma 0
        "def f(a):\n    out = list()\n    for v in a:\n        out.append(v)\n",
    ],
)
def test_list_comp_excluded(code: str) -> None:
    assert channel_values(code, "list_comp") == []


def test_list_comp_read_before_loop_is_allowed() -> None:
    code = "def f(a, v):\n    print(v)\n    out = []\n    for v in a:\n        out.append(v)\n"
    assert channel_values(code, "list_comp") == [0]


# ---------------------------------------------------------------------- 5. ternary

IF_FORM = """
def f(a, b):
    if a:
        x = b
    else:
        x = 1
    return x
"""
EXP_FORM = """
def f(a, b):
    x = b if a else 1
    return x
"""


def test_ternary_forms() -> None:
    assert channel_values(IF_FORM, "ternary") == [0]
    assert channel_values(EXP_FORM, "ternary") == [1]


@pytest.mark.parametrize(
    "code",
    [
        # bersagli diversi
        "def f(a):\n    if a:\n        x = 1\n    else:\n        y = 2\n",
        # due istruzioni in un ramo
        "def f(a):\n    if a:\n        x = 1\n        g()\n    else:\n        x = 2\n",
        # nessun else
        "def f(a):\n    if a:\n        x = 1\n",
        # rami non puri
        "def f(a):\n    if a:\n        x = g()\n    else:\n        x = 2\n",
        "def f(a):\n    x = g() if a else 2\n",
        # elif: l'If interno è l'unico elemento dell'orelse
        "def f(a, b):\n    if a:\n        g()\n"
        "    elif b:\n        x = 1\n    else:\n        x = 0\n",
        # forma 1 nell'orelse di un If (la sua forma 0 sarebbe un elif)
        "def f(a, b):\n    if a:\n        pass\n    else:\n        x = 1 if b else 2\n",
        # rami che sarebbero siti di aug_assign
        "def f(a, x):\n    x = x + 1 if a else x - 1\n",
        "def f(a, x):\n    x = 1 + x if a else 0\n",
        "def f(a, x):\n    if a:\n        x = x / 2\n    else:\n        x = 0\n",
        # IfExp annidato
        "def f(a, b):\n    x = 1 if a else (2 if b else 3)\n",
        # bersaglio non Name
        "def f(a, o):\n    o.x = 1 if a else 2\n",
    ],
)
def test_ternary_excluded(code: str) -> None:
    assert channel_values(code, "ternary") == []


# ---------------------------------------------------------------------- 6. operand_order


@pytest.mark.parametrize(
    "expr,value",
    [("a + 1", 0), ("1 + a", 1), ("a.b * 2.0", 0), ("3 * a[0]", 1)],
)
def test_operand_order_forms(expr: str, value: int) -> None:
    assert channel_values(f"def f(a):\n    return {expr}\n", "operand_order") == [value]


@pytest.mark.parametrize(
    "expr",
    [
        "a - 1",  # operatore non commutativo
        "a + b",  # nessuna costante
        "1 + 2",  # due costanti
        "a + True",  # bool
        "a + 1j",  # complesso
        "a + 's'",  # stringa
        "g(a) + 1",  # Call (kind 4)
        "-a + 1",  # UnaryOp (kind 5)
        "a + 1 + 2",  # figlio di BinOp con lo stesso operatore; l'esterno ha BinOp
    ],
)
def test_operand_order_excluded(expr: str) -> None:
    assert channel_values(f"def f(a):\n    return {expr}\n", "operand_order") == []


def test_operand_order_child_of_other_operator_is_site() -> None:
    assert channel_values("def f(a):\n    return (a * 2) + b\n", "operand_order") == [0]


def test_operand_order_excluded_when_it_would_make_aug_assign() -> None:
    assert channel_values("def f(x):\n    x = 1 + x\n", "operand_order") == []
    assert channel_values("def f(x):\n    x = 2 * x\n", "operand_order") == [1]
    assert channel_values("def f(x, y):\n    y = 1 + x\n", "operand_order") == [1]


# ---------------------------------------------------------------------- 7. empty_coll


@pytest.mark.parametrize(
    "expr,value",
    [("[]", 0), ("{}", 0), ("list()", 1), ("dict()", 1)],
)
def test_empty_coll_forms(expr: str, value: int) -> None:
    assert channel_values(f"def f():\n    return {expr}\n", "empty_coll") == [value]


@pytest.mark.parametrize(
    "expr",
    ["[1]", "{1: 2}", "{**a}", "list(a)", "dict(a=1)", "set()", "()", "list[int]"],
)
def test_empty_coll_excluded(expr: str) -> None:
    assert channel_values(f"def f(a):\n    return {expr}\n", "empty_coll") == []


@pytest.mark.parametrize(
    "code",
    [
        "list = tuple\ndef f():\n    return list()\n",
        "def f(list):\n    return list()\n",
        "from x import y as list\ndef f():\n    return list()\n",
        "def list():\n    pass\ndef f():\n    return list()\n",
    ],
)
def test_empty_coll_rebound_builtin(code: str) -> None:
    assert channel_values(code, "empty_coll") == []


def test_empty_coll_rebound_only_affects_that_name() -> None:
    code = "def f(list):\n    return dict(), [], {}\n"
    assert channel_values(code, "empty_coll") == [1, 0, 0]


def test_empty_list_call_before_append_loop_is_not_a_site() -> None:
    code = "def f(a):\n    out = list()\n    for v in a:\n        out.append(v)\n    return out\n"
    assert channel_values(code, "empty_coll") == []
    assert channel_values(code, "list_comp") == []


def test_empty_list_before_non_qualifying_loop_is_empty_coll() -> None:
    code = "def f(a):\n    out = []\n    for v in a:\n        out.append(v)\n    return v\n"
    assert channel_values(code, "list_comp") == []
    assert channel_values(code, "empty_coll") == [0]


# ---------------------------------------------------------------------- 8. none_check


@pytest.mark.parametrize(
    "expr,value",
    [
        ("a is None", 0),
        ("a is not None", 0),
        ("a == None", 1),
        ("a != None", 1),
        ("a.b is None", 0),
    ],
)
def test_none_check_forms(expr: str, value: int) -> None:
    assert channel_values(f"def f(a):\n    return {expr}\n", "none_check") == [value]


@pytest.mark.parametrize(
    "expr", ["None is a", "g(a) is None", "a is None is None", "a < None", "a in None"]
)
def test_none_check_excluded(expr: str) -> None:
    assert channel_values(f"def f(a):\n    return {expr}\n", "none_check") == []


# ---------------------------------------------------------------------- guards=False


@pytest.mark.parametrize(
    "code,channel",
    [
        ("def f(x, y):\n    x = x * y\n", "aug_assign"),
        ("def f(x):\n    x |= g()\n", "aug_assign"),
        ("def f(a):\n    return len(a) < g(a) + 1\n", "compare_dir"),
        ("def f(a):\n    return g(a) is None\n", "none_check"),
        ("def f(a):\n    return g(a) + 1\n", "operand_order"),
        ("def f(a):\n    x = g() if a else 2\n", "ternary"),
        (
            "def f(a):\n    out = []\n    for v in a:\n        out.append(v)\n    return v\n",
            "list_comp",
        ),
        ("def f(list):\n    return list()\n", "empty_coll"),
    ],
)
def test_no_guards_adds_sites(code: str, channel: str) -> None:
    assert channel_values(code, channel) == []
    assert len(channel_values(code, channel, guards=False)) == 1


@pytest.mark.parametrize(
    "code,channel",
    [
        ("def f(a, b):\n    return a < b\n", "compare_dir"),  # stesso kind: nessuna forma
        ("def f(a):\n    return a == None\n", "equality_dir"),
        ("def f(a):\n    return 1 + 2\n", "operand_order"),
        ("def f(x):\n    x = 1 + x\n", "operand_order"),  # non interferenza
    ],
)
def test_no_guards_keeps_structural_conditions(code: str, channel: str) -> None:
    assert channel_values(code, channel, guards=False) == []


# ---------------------------------------------------------------------- non interferenza

# Coppie (forma 0, forma 1) dello stesso codice che differiscono per la forma di un solo sito:
# le chiavi (fid, canale, rango) devono coincidere e deve cambiare un solo valore.
FORM_PAIRS: list[tuple] = [
    ("def f(x):\n    x = x + 1\n    return x < 2\n", "def f(x):\n    x += 1\n    return x < 2\n"),
    ("def f(a, x):\n    return a < 1\n", "def f(a, x):\n    return 1 > a\n"),
    ("def f(a):\n    return 1 == a.b\n", "def f(a):\n    return a.b == 1\n"),
    (LOOP, COMP),
    (IF_FORM, EXP_FORM),
    ("def f(a):\n    return a + 1, []\n", "def f(a):\n    return 1 + a, []\n"),
    ("def f(a):\n    y = a + 1\n", "def f(a):\n    y = 1 + a\n"),
    ("def f(a):\n    y = []\n    return y\n", "def f(a):\n    y = list()\n    return y\n"),
    ("def f(a):\n    return a is None\n", "def f(a):\n    return a == None\n"),
    # ternario con un ramo che contiene un sito 6: solo il ternario cambia
    (
        "def f(a, b):\n    if a:\n        y = b * 2\n    else:\n        y = 0\n",
        "def f(a, b):\n    y = b * 2 if a else 0\n",
    ),
    # ternario con rami che sono siti 7
    (
        "def f(a):\n    if a:\n        y = []\n    else:\n        y = {}\n",
        "def f(a):\n    y = [] if a else {}\n",
    ),
    # aug_assign con e che contiene un sito 6
    ("def f(x, y):\n    x = x / (y * 2)\n", "def f(x, y):\n    x /= y * 2\n"),
]


@pytest.mark.parametrize("form0,form1", FORM_PAIRS)
def test_changing_one_form_keeps_site_set(form0: str, form1: str) -> None:
    for canonical in ("kind", "paper"):
        a = keys_values(form0, canonical=canonical)
        b = keys_values(form1, canonical=canonical)
        assert [k for k, _ in a] == [k for k, _ in b]
        diff = [k for (k, va), (_, vb) in zip(a, b) if va != vb]
        assert len(diff) == 1


@pytest.mark.parametrize(
    "form0,form1",
    [
        # x = 1 + x non è sito 6 (con x + 1 sarebbe sito 1): nessun sito in entrambe
        ("def f(x):\n    x = 1 + x\n", None),
        # if con rami aug: solo i siti 1 (il ternario non è sito)
        ("def f(a, x):\n    if a:\n        x = x + 1\n    else:\n        x = x - 1\n", None),
    ],
)
def test_interfering_candidates_are_stable(form0: str, form1: object) -> None:
    sites = read(form0)
    assert all(s.channel != "ternary" for s in sites)
    assert all(s.channel != "operand_order" for s in sites)


def test_values_are_binary() -> None:
    code = "\n".join(p for pair in FORM_PAIRS for p in pair)
    for site in read(code):
        assert site.value in (0, 1)
