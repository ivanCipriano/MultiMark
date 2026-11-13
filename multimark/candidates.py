"""Inventario dei canali candidati (passo P0-bis, prima di P1).

Conta per campione, **sull'``ast`` e senza trasformare nulla**, le occorrenze di 23 pattern che
potrebbero diventare canali (molti vengono dalle trasformazioni di Zottarelli, codici ``T<n>``).
Ogni pattern ha un nome breve e un contatore per ciascuna forma (``cand_<nome>_f<i>``). Il
conteggio serve solo a decidere quali canali valga la pena studiare: **nessun pattern qui è un
canale**. Le condizioni semantiche (tipi, purezza, equivalenza) non sono verificate, salvo dove
indicato.

Limiti dovuti alla lettura sull'``ast`` (regola fissa: nessun canale che dipenda da spazi, a capo
o commenti):

- ``i`` (``elif`` / ``else: if``, T9): le due scritture danno lo **stesso** ``ast``
  (``orelse = [If]``); si conta solo l'occorrenza, con un contatore unico. Non può essere un canale.
- ``r`` (costanti): ``0.5``/``.5`` e ``1e3``/``1000.0`` danno lo stesso ``Constant``; si conta solo
  ``c1 ** c2`` fra costanti (``10**3``), la cui altra forma (``1000``) non è riconoscibile.
- ``p.f1``, ``w.f1`` coincidono con ``e.f1`` (test di verità ``a`` / ``not a`` in una condizione) e
  ``w.f2`` è il sottoinsieme ``len(x) == 0`` di ``e.f0``: sono contatori ripetuti per leggibilità.
- I pattern si sovrappongono (es. ``range(n)`` di ``k.f1`` è anche dentro ``b.f0``; ``h.f0`` è
  anche ``a.f0``): sommare i contatori dà un **limite superiore**.

**Stima di capacità: tre varianti** (decisioni di Ivan, 13 novembre 2026).

- ``prudent``: solo le forme di ``Pattern.site_forms``, cioè quelle che si trasformano nell'altra
  senza conoscere i tipi. Restano fuori ``e.f1`` (``if a:`` come forma di ``len(a) > 0``),
  ``g.f0`` (``s.split()`` con ``s`` di tipo ignoto), ``h.f2`` (``return c``), i pattern ``p`` e
  ``w`` e ``u`` (già canale ``aug_assign``).
- ``all_forms``: tutte le forme, compresi ``p`` e ``w`` (senza i contatori ripetuti).
- ``no_overlap``: le forme della variante prudente, senza doppi conteggi. Ogni occorrenza
  «possiede» i nodi che la trasformazione riscriverebbe (come gli insiemi ``owned`` dei canali).
  Priorità: prima i siti degli otto canali esistenti (un'occorrenza che tocca un nodo già sito non
  conta), poi i pattern in ordine di frequenza decrescente; un nodo contato da un pattern non conta
  per i successivi. La frequenza della classifica è quella delle occorrenze che non toccano siti
  esistenti.

``i`` ed ``r`` non possono essere canali (le due scritture danno lo stesso ``ast``) e ``u`` è già un
canale: sono contati solo come nota e restano fuori da tutte le stime.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Optional

from multimark._astindex import (
    AstIndex,
    is_numeric_constant,
    is_pure,
    iter_preorder,
    module_bindings,
)


@dataclass(frozen=True)
class Pattern:
    """Pattern candidato: lettera della richiesta, nome breve, descrizione delle forme, fonte."""

    letter: str
    name: str
    forms: tuple[str, ...]
    source: str = ""
    site_forms: tuple[int, ...] = ()
    note: str = ""
    #: identificatori delle forme (default ``f0``, ``f1``, ...); ``g`` ha anche ``f0_guarded``
    form_ids: tuple[str, ...] = ()

    def form_id(self, form: int) -> str:
        return self.form_ids[form] if self.form_ids else f"f{form}"

    def counter(self, form: int) -> str:
        return f"cand_{self.name}_{self.form_id(form)}"

    @property
    def counters(self) -> tuple[str, ...]:
        return tuple(self.counter(i) for i in range(len(self.forms)))


PATTERNS: tuple[Pattern, ...] = (
    Pattern("a", "else_return", ("if c: return X / else: return Y",
            "if c: return X / return Y (senza else)"), "T16", (0, 1)),
    Pattern("b", "range_len", ("for i in range(len(a)) con a[i] nel corpo",
            "for i, x in enumerate(a)"), "T38", (0, 1)),
    Pattern("c", "square", ("x * x (x puro)", "x ** 2"), "T7", (0, 1)),
    Pattern("d", "not_eq", ("not a == b", "a != b"), "", (0, 1)),
    Pattern("e", "len_test", ("len(a) == 0 / len(a) > 0, != 0, >= 1",
            "a / not a in una condizione"), "",
            (0,), "semantica da verificare (tipo di a)"),
    Pattern("f", "slice_bound", ("a[0:n] / a[i:len(a)]", "a[:n] / a[i:]"), "T2", (0, 1)),
    Pattern("g", "str_method", ("s.split(...), s.join(...), s.strip(...) ecc.",
            "str.split(s, ...) ecc.",
            "s.m(...) con s stringa garantita: letterale, f-string, input/str/repr/format(...) "
            "(sottoinsieme di f0)"),
            "T39", (1, 2), "tipo di s ignoto nella forma 0 senza guardia",
            ("f0", "f1", "f0_guarded")),
    Pattern("h", "bool_return", ("if c: return True / else: return False", "return bool(c)",
            "return <Compare|BoolOp|not>"), "", (0, 1)),
    Pattern("i", "elif", ("elif / else: if (stesso ast)",), "T9", (),
            "le due scritture non si distinguono sull'ast"),
    Pattern("j", "nested_if", ("if a: if b: (senza else)", "if a and b: (senza else)"), "T17",
            (0, 1)),
    Pattern("k", "range_zero", ("range(0, n)", "range(n)"), "", (0, 1)),
    Pattern("l", "or_eq", ("a == b or a == c", "a in (b, c)"), "T6", (0, 1),
            "a valutato una o più volte"),
    Pattern("m", "identity_comp", ("[x for x in a]", "list(a)"), "T31", (0, 1)),
    Pattern("n", "sorted_rev", ("sorted(a)[::-1]", "sorted(a, reverse=True)"), "", (0, 1),
            "ordine degli elementi uguali da verificare (stabilità)"),
    Pattern("o", "str_build", ("f-string", "'...'.format(...)", "concatenazione + con str()"),
            "", (0, 1, 2)),
    Pattern("p", "bool_cmp", ("a == True / a == False / a is True / a is False",
            "a / not a in una condizione (= e.f1)"), "", (), "non equivalenti senza tipi"),
    Pattern("q", "while_break", ("while True: con un solo if ...: break in testa",
            "while not cond:"), "", (0, 1)),
    Pattern("r", "const_pow", ("c1 ** c2 fra costanti numeriche (10**3)",), "", (),
            "1000 / 1e3 / 1000.0 non si distinguono sull'ast"),
    Pattern("s", "get_none", ("d.get(k, None)", "d.get(k)"), "", (0, 1)),
    Pattern("t", "return_none", ("return None", "return"), "", (0, 1)),
    Pattern("u", "aug_inc", ("x = x ± c", "x ±= c"), "", (),
            "già coperto da aug_assign: solo per confronto"),
    Pattern("v", "max_ternary", ("max(a, b)", "a if a > b else b"), "", (0, 1),
            "con pareggi max restituisce il primo argomento"),
    Pattern("w", "empty_str", ('s == ""', "not s / s in una condizione (= e.f1)",
            "len(s) == 0 (sottoinsieme di e.f0)"), "", (), "non equivalenti senza tipi"),
)  # fmt: skip

PATTERNS_BY_NAME = {p.name: p for p in PATTERNS}
COUNTERS: tuple[str, ...] = tuple(c for p in PATTERNS for c in p.counters)

#: Funzioni il cui risultato è sempre ``str`` (guardia di ``g.f0_guarded``, canale 15 di
#: §3.3.1b), se non ridefinite nel modulo.
STR_PRODUCERS = frozenset({"input", "str", "repr", "format"})

#: Metodi di ``str`` contati da ``g`` (T39); elenco confermato da Ivan (13 novembre 2026).
STR_METHODS = frozenset(
    {"split", "join", "strip", "lstrip", "rstrip", "lower", "upper", "replace", "startswith",
     "endswith"}
)  # fmt: skip

_LOOPS = (ast.For, ast.AsyncFor, ast.While)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


# ---------------------------------------------------------------------- utilità


def _same(a: ast.AST, b: ast.AST) -> bool:
    """Stesso sottoalbero (``ast.dump`` senza posizioni)."""
    return ast.dump(a) == ast.dump(b)


def _simple(e: ast.AST) -> bool:
    return isinstance(e, (ast.Name, ast.Attribute, ast.Subscript))


def _call_to(node: ast.AST, name: str, n_args: Optional[int] = None) -> bool:
    """``name(...)`` con ``n_args`` argomenti posizionali (se dato), senza ``*args``."""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
        return False
    if node.func.id != name or any(isinstance(a, ast.Starred) for a in node.args):
        return False
    return n_args is None or len(node.args) == n_args


def _const(e: ast.AST, value: object) -> bool:
    """Costante uguale a ``value`` dello stesso tipo (``0`` non è ``False``)."""
    return isinstance(e, ast.Constant) and type(e.value) is type(value) and e.value == value


def _single_return(body: list) -> bool:
    return len(body) == 1 and isinstance(body[0], ast.Return)


def _single_compare(node: ast.AST, ops: tuple) -> bool:
    return isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ops)


def _is_len_of(e: ast.AST) -> bool:
    return _call_to(e, "len", 1) and not e.keywords  # type: ignore[attr-defined]


def _condition_atoms(e: ast.AST) -> list:
    if isinstance(e, ast.BoolOp):
        return [a for v in e.values for a in _condition_atoms(v)]
    return [e]


def _breaks_in(stmts: list) -> int:
    """``break`` che appartengono al ciclo (esclusi cicli e funzioni annidati)."""
    n = 0
    stack = list(stmts)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Break):
            n += 1
        elif not isinstance(node, (*_LOOPS, *_SCOPES)):
            stack.extend(ast.iter_child_nodes(node))
        elif isinstance(node, _LOOPS):
            stack.extend(node.orelse)  # il break nell'else di un ciclo annidato è del ciclo esterno
    return n


def _str_call(e: ast.AST) -> bool:
    return _call_to(e, "str")


def _add_chain(e: ast.AST) -> list:
    if isinstance(e, ast.BinOp) and isinstance(e.op, ast.Add):
        return _add_chain(e.left) + _add_chain(e.right)
    return [e]


# ---------------------------------------------------------------------- conteggio


class _Counter:
    def __init__(self, bound: frozenset[str] = frozenset()) -> None:
        self.bound = bound  # nomi con un binding nel modulo (builtin ridefiniti)
        self.counts = {c: 0 for c in COUNTERS}
        # (contatore, nodo, id dei nodi posseduti) in ordine di visita
        self.hits: list[tuple[str, ast.AST, frozenset[int]]] = []

    def add(self, name: str, form: int, node: ast.AST, *owned: ast.AST) -> None:
        """Registra un'occorrenza; ``owned`` sono i nodi, oltre a ``node``, che la trasformazione
        riscriverebbe (servono alla stima senza sovrapposizioni)."""
        key = PATTERNS_BY_NAME[name].counter(form)
        self.counts[key] += 1
        self.hits.append((key, node, frozenset(id(n) for n in (node, *owned))))


def _visit(node: ast.AST, index: AstIndex, out: _Counter) -> None:
    parent = index.parent_of(node)

    if isinstance(node, ast.If):
        # a, h: return nei due rami / return dopo l'if
        if _single_return(node.body):
            if node.orelse and _single_return(node.orelse):
                out.add("else_return", 0, node)
                r0, r1 = node.body[0], node.orelse[0]
                assert isinstance(r0, ast.Return) and isinstance(r1, ast.Return)
                if r0.value is not None and r1.value is not None:
                    if _const(r0.value, True) and _const(r1.value, False):
                        out.add("bool_return", 0, node, r0, r1)
            elif not node.orelse and isinstance(index.next_sibling(node), ast.Return):
                out.add("else_return", 1, node)
        # i: orelse fatto di un solo If
        if len(node.orelse) == 1 and isinstance(node.orelse[0], ast.If):
            out.add("elif", 0, node)
        # j: if annidati senza else / if a and b
        if not node.orelse:
            inner = node.body[0] if len(node.body) == 1 else None
            if isinstance(inner, ast.If) and not inner.orelse:
                out.add("nested_if", 0, node, inner)
            if isinstance(node.test, ast.BoolOp) and isinstance(node.test.op, ast.And):
                out.add("nested_if", 1, node, node.test)

    if isinstance(node, (ast.If, ast.While, ast.IfExp, ast.Assert)):
        # e.f1, p.f1, w.f1: test di verità in una condizione
        for atom in _condition_atoms(node.test):
            if _simple(atom) or (
                isinstance(atom, ast.UnaryOp)
                and isinstance(atom.op, ast.Not)
                and _simple(atom.operand)
            ):
                for name in ("len_test", "bool_cmp", "empty_str"):
                    out.add(name, 1, atom, *ast.iter_child_nodes(atom))

    if type(node) is ast.For:
        # b: range(len(a)) con a[i] / enumerate(a)
        it, target = node.iter, node.target
        if (
            isinstance(target, ast.Name) and _call_to(it, "range", 1) and _is_len_of(it.args[0])  # type: ignore[attr-defined]
        ):
            seq = it.args[0].args[0]  # type: ignore[attr-defined]
            if any(
                isinstance(n, ast.Subscript)
                and _same(n.value, seq)
                and isinstance(n.slice, ast.Name)
                and n.slice.id == target.id
                for stmt in node.body
                for n in iter_preorder(stmt)
            ):
                out.add("range_len", 0, node, target, it, it.args[0])  # type: ignore[attr-defined]
        if (
            isinstance(target, ast.Tuple)
            and len(target.elts) == 2
            and all(isinstance(e, ast.Name) for e in target.elts)
            and _call_to(it, "enumerate", 1)
            and not it.keywords  # type: ignore[attr-defined]
        ):
            out.add("range_len", 1, node, target, it)

    if isinstance(node, ast.BinOp):
        # c: x * x / x ** 2
        if isinstance(node.op, ast.Mult) and _same(node.left, node.right) and is_pure(node.left):
            out.add("square", 0, node)
        if isinstance(node.op, ast.Pow) and _const(node.right, 2):
            out.add("square", 1, node)
        # r: costante ** costante
        if (
            isinstance(node.op, ast.Pow)
            and is_numeric_constant(node.left)
            and is_numeric_constant(node.right)
        ):
            out.add("const_pow", 0, node)
        # o.f2: catena di + più esterna con str(...)
        if isinstance(node.op, ast.Add) and not (
            isinstance(parent, ast.BinOp) and isinstance(parent.op, ast.Add)
        ):
            if any(_str_call(e) for e in _add_chain(node)):
                out.add("str_build", 2, node)

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        # d.f0
        if _single_compare(node.operand, (ast.Eq,)):
            out.add("not_eq", 0, node, node.operand)

    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        op, left, right = node.ops[0], node.left, node.comparators[0]
        if isinstance(op, ast.NotEq):
            out.add("not_eq", 1, node)
        # e.f0: len(a) == 0, len(a) > 0, len(a) != 0, len(a) >= 1; w.f2: len(s) == 0
        if _is_len_of(left) and (
            (_const(right, 0) and isinstance(op, (ast.Eq, ast.Gt, ast.NotEq)))
            or (_const(right, 1) and isinstance(op, ast.GtE))
        ):
            out.add("len_test", 0, node, left)
        if _is_len_of(left) and _const(right, 0) and isinstance(op, ast.Eq):
            out.add("empty_str", 2, node, left)
        # p.f0: confronti con True/False
        if isinstance(op, (ast.Eq, ast.Is)) and any(
            _const(e, True) or _const(e, False) for e in (left, right)
        ):
            out.add("bool_cmp", 0, node)
        # w.f0: s == ""
        if isinstance(op, ast.Eq) and (_const(left, "") or _const(right, "")):
            out.add("empty_str", 0, node)
        # l.f1: a in (b, c)
        if isinstance(op, ast.In) and isinstance(right, (ast.Tuple, ast.List, ast.Set)):
            out.add("or_eq", 1, node, right)

    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
        sl = node.slice
        # f: limiti superflui
        if sl.step is None:
            explicit = (sl.lower is not None and _const(sl.lower, 0) and sl.upper is not None) or (
                sl.lower is not None
                and sl.upper is not None
                and _is_len_of(sl.upper)
                and _same(sl.upper.args[0], node.value)  # type: ignore[attr-defined]
            )
            if explicit:
                out.add("slice_bound", 0, node, sl)
            elif (sl.lower is None) != (sl.upper is None):
                out.add("slice_bound", 1, node, sl)
        # n.f0: sorted(a)[::-1]
        step = sl.step
        minus_one = _const(step, -1) if step is not None else False
        if (
            step is not None
            and isinstance(step, ast.UnaryOp)
            and isinstance(step.op, ast.USub)
            and _const(step.operand, 1)
        ):
            minus_one = True
        if minus_one and sl.lower is None and sl.upper is None and _call_to(node.value, "sorted"):
            out.add("sorted_rev", 0, node, sl, node.value)

    if isinstance(node, ast.Call):
        func = node.func
        # g: metodi di str
        if isinstance(func, ast.Attribute) and func.attr in STR_METHODS:
            is_type_call = isinstance(func.value, ast.Name) and func.value.id == "str"
            out.add("str_method", 1 if is_type_call else 0, node, func)
            if not is_type_call and _str_receiver(func.value, out.bound):
                out.add("str_method", 2, node, func)
        # k: range(0, n) / range(n)
        if _call_to(node, "range") and not node.keywords:
            if len(node.args) == 2 and _const(node.args[0], 0):
                out.add("range_zero", 0, node)
            elif len(node.args) == 1:
                out.add("range_zero", 1, node)
        # m.f1: list(a)
        if _call_to(node, "list", 1) and not node.keywords:
            out.add("identity_comp", 1, node)
        # n.f1: sorted(a, reverse=True)
        if _call_to(node, "sorted") and any(
            k.arg == "reverse" and _const(k.value, True) for k in node.keywords
        ):
            out.add("sorted_rev", 1, node)
        # o.f1: '...'.format(...)
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "format"
            and isinstance(func.value, ast.Constant)
            and isinstance(func.value.value, str)
        ):
            out.add("str_build", 1, node, func)
        # s: d.get(k, None) / d.get(k)
        if isinstance(func, ast.Attribute) and func.attr == "get" and not node.keywords:
            if len(node.args) == 2 and _const(node.args[1], None):
                out.add("get_none", 0, node)
            elif len(node.args) == 1:
                out.add("get_none", 1, node)
        # v.f0: max(a, b)
        if _call_to(node, "max", 2) and not node.keywords:
            out.add("max_ternary", 0, node)

    if isinstance(node, ast.Return):
        # h.f1, h.f2, t
        value = node.value
        if value is None:
            out.add("return_none", 1, node)
        else:
            if _const(value, None):
                out.add("return_none", 0, node)
            if _call_to(value, "bool", 1) and not value.keywords:  # type: ignore[attr-defined]
                out.add("bool_return", 1, node, value)
            if isinstance(value, (ast.Compare, ast.BoolOp)) or (
                isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.Not)
            ):
                out.add("bool_return", 2, node)

    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        # l.f0: a == b or a == c
        values = node.values
        if (
            all(_single_compare(v, (ast.Eq,)) for v in values)
            and all(
                _same(v.left, values[0].left)  # type: ignore[attr-defined]
                for v in values[1:]
            )
        ):
            out.add("or_eq", 0, node, *values)

    if isinstance(node, ast.ListComp) and len(node.generators) == 1:
        # m.f0: [x for x in a]
        gen = node.generators[0]
        if (
            not gen.ifs
            and not gen.is_async
            and isinstance(gen.target, ast.Name)
            and isinstance(node.elt, ast.Name)
            and node.elt.id == gen.target.id
        ):
            out.add("identity_comp", 0, node, gen)

    if isinstance(node, ast.JoinedStr) and not isinstance(parent, ast.FormattedValue):
        out.add("str_build", 0, node)  # o.f0 (non le format spec annidate)

    if isinstance(node, ast.While):
        # q
        first = node.body[0]
        if (
            _const(node.test, True)
            and isinstance(first, ast.If)
            and len(first.body) == 1
            and isinstance(first.body[0], ast.Break)
            and not first.orelse
            and _breaks_in(node.body) == 1
        ):
            out.add("while_break", 0, node, first, first.body[0])
        if isinstance(node.test, ast.UnaryOp) and isinstance(node.test.op, ast.Not):
            out.add("while_break", 1, node, node.test)

    if isinstance(node, ast.IfExp) and _single_compare(
        node.test, (ast.Gt, ast.GtE, ast.Lt, ast.LtE)
    ):
        # v.f1: a if a > b else b (o b if a < b else a)
        test = node.test
        assert isinstance(test, ast.Compare)
        a, b = test.left, test.comparators[0]
        if isinstance(test.ops[0], (ast.Gt, ast.GtE)):
            hit = _same(node.body, a) and _same(node.orelse, b)
        else:
            hit = _same(node.body, b) and _same(node.orelse, a)
        if hit:
            out.add("max_ternary", 1, node, test)

    # u: x = x ± c / x ±= c (confronto con aug_assign)
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        t, v = node.targets[0], node.value
        if (
            isinstance(t, ast.Name)
            and isinstance(v, ast.BinOp)
            and isinstance(v.op, (ast.Add, ast.Sub))
            and isinstance(v.left, ast.Name)
            and v.left.id == t.id
            and is_numeric_constant(v.right)
        ):
            out.add("aug_inc", 0, node, v)
    if (
        isinstance(node, ast.AugAssign)
        and isinstance(node.target, ast.Name)
        and isinstance(node.op, (ast.Add, ast.Sub))
        and is_numeric_constant(node.value)
    ):
        out.add("aug_inc", 1, node)


def _str_receiver(recv: ast.AST, bound: frozenset[str]) -> bool:
    """Il ricevitore è certamente una ``str``: letterale stringa, f-string, o chiamata a
    ``input``/``str``/``repr``/``format`` non ridefinite; ``str`` stesso non ridefinito (la forma 1
    scrive ``str.m(...)``)."""
    if "str" in bound:
        return False
    if isinstance(recv, ast.Constant) and isinstance(recv.value, str):
        return True
    if isinstance(recv, ast.JoinedStr):
        return True
    return (
        isinstance(recv, ast.Call)
        and isinstance(recv.func, ast.Name)
        and recv.func.id in STR_PRODUCERS
        and recv.func.id not in bound
    )


def scan(index: AstIndex) -> _Counter:
    out = _Counter(frozenset(module_bindings(index.tree)))
    for node in index.order:
        _visit(node, index, out)
    return out


def count_candidates(code: str) -> Optional[dict[str, int]]:
    """Contatori ``cand_<nome>_f<i>`` di un campione; ``None`` se ``ast.parse`` fallisce."""
    try:
        index = AstIndex.from_code(code)
    except (SyntaxError, ValueError):
        return None
    return scan(index).counts


def candidate_hits(code: str) -> list[tuple[str, int, int, str]]:
    """Occorrenze ``(contatore, riga, colonna, testo del nodo)`` ordinate per posizione (per i
    report; il testo è la prima riga del segmento di sorgente)."""
    out = []
    for key, node, _ in scan(AstIndex.from_code(code)).hits:
        lines = (ast.get_source_segment(code, node) or "").splitlines()
        text = lines[0].strip() if lines else ""
        out.append((key, getattr(node, "lineno", 0), getattr(node, "col_offset", 0), text))
    return sorted(out, key=lambda h: (h[1], h[2], COUNTERS.index(h[0])))


# ---------------------------------------------------------------------- aggregazione

ESTIMATE_KS = (3, 5, 8)
ESTIMATE_THRESHOLDS = (8, 13)


VARIANTS = ("prudent", "all_forms", "no_overlap")


def sample_row(code: str) -> dict:
    """Riga per campione: contatori, ``parse_ok``, ``n_sites_total`` dell'inventario e, per la
    variante ``no_overlap``, le occorrenze con i nodi posseduti (``_hits``) e i nodi dei siti
    strutturali (``_site_owned``), come posizioni di visita."""
    from multimark.channels import ReadOptions
    from multimark.inventory import inventory_code
    from multimark.sites import find_sites

    try:
        index = AstIndex.from_code(code)
    except (SyntaxError, ValueError):
        return {"parse_ok": False}
    result = scan(index)
    pos = index.position
    # P0-bis: i candidati si stimano sopra gli otto canali di MCSS (channels="mcss8").
    sites = find_sites(index, ReadOptions(channels="mcss8"))
    site_owned = frozenset(pos[i] for site in sites for i in site.owned)
    hits = [(key, frozenset(pos[i] for i in owned)) for key, _, owned in result.hits]
    inv = inventory_code(code, channels="mcss8")
    return {
        "parse_ok": True,
        "n_sites_total": inv["n_sites_total"],
        **result.counts,
        "_hits": hits,
        "_site_owned": site_owned,
    }


def _duplicate_counter(pattern: Pattern, form: int) -> bool:
    """Contatori ripetuti di altri pattern (``p.f1``, ``w.f1``, ``w.f2``)."""
    return (pattern.name, form) in {("bool_cmp", 1), ("empty_str", 1), ("empty_str", 2)}


def estimate_counters(pattern: Pattern, all_forms: bool = False) -> tuple[str, ...]:
    """Contatori di un pattern che entrano nella stima: ``site_forms`` (prudente) o tutte le
    forme. ``u`` (già ``aug_assign``), ``i`` e ``r`` (stesso ``ast``) non entrano mai; i contatori
    ripetuti (``p.f1``, ``w.f1``, ``w.f2``) nemmeno."""
    if pattern.name in ("aug_inc", "elif", "const_pow"):
        return ()
    forms = range(len(pattern.forms)) if all_forms else pattern.site_forms
    return tuple(
        pattern.counter(i)
        for i in forms
        if not _duplicate_counter(pattern, i) and not (all_forms and _subset_counter(pattern, i))
    )


def _subset_counter(pattern: Pattern, form: int) -> bool:
    """Contatori che sono un sottoinsieme di un'altra forma dello stesso pattern
    (``g.f0_guarded`` ⊂ ``g.f0``): nella variante ``all_forms`` non si sommano."""
    return pattern.form_id(form) == "f0_guarded"


def summarize_candidates(rows: list) -> dict:
    """Per contatore: totale, media per campione, frazione di campioni con almeno 1."""
    ok = [r for r in rows if r.get("parse_ok")]
    n = len(ok)
    out: dict = {"n_samples": len(rows), "n_parsed": n, "counters": {}}
    for counter in COUNTERS:
        total = sum(r[counter] for r in ok)
        out["counters"][counter] = {
            "total": total,
            "mean": total / n if n else float("nan"),
            "frac_ge_1": sum(1 for r in ok if r[counter] > 0) / n if n else float("nan"),
        }
    return out


def _free_hits(row: dict, pattern: Pattern) -> int:
    """Occorrenze (forme prudenti) del pattern che non toccano siti strutturali esistenti."""
    counters = estimate_counters(pattern)
    return sum(
        1 for key, owned in row["_hits"] if key in counters and not owned & row["_site_owned"]
    )


def rank_patterns(rows: list, variant: str = "prudent") -> list[tuple[str, int]]:
    """Pattern ordinati per frequenza decrescente (a pari merito, per lettera); esclusi quelli
    senza contatori di stima. Per ``no_overlap`` la frequenza conta solo le occorrenze che non
    toccano siti esistenti."""
    if variant not in VARIANTS:
        raise ValueError(f"variant must be one of {VARIANTS}: {variant!r}")
    ok = [r for r in rows if r.get("parse_ok")]
    scored = []
    for pattern in PATTERNS:
        counters = estimate_counters(pattern, all_forms=variant == "all_forms")
        if not counters:
            continue
        if variant == "no_overlap":
            total = sum(_free_hits(r, pattern) for r in ok)
        else:
            total = sum(r[c] for r in ok for c in counters)
        scored.append((pattern.name, total, pattern.letter))
    scored.sort(key=lambda x: (-x[1], x[2]))
    return [(name, total) for name, total, _ in scored]


def added_sites(row: dict, names: list, variant: str = "prudent") -> int:
    """Siti in più per un campione se i pattern ``names`` (in quest'ordine) diventassero canali.

    ``prudent`` e ``all_forms`` sommano i contatori (limite superiore). ``no_overlap`` assegna ogni
    nodo al più a un sito: prima ai siti strutturali esistenti, poi ai pattern nell'ordine dato,
    e dentro un pattern in ordine di visita."""
    if variant == "no_overlap":
        claimed = set(row["_site_owned"])
        total = 0
        for name in names:
            counters = estimate_counters(PATTERNS_BY_NAME[name])
            for key, owned in row["_hits"]:
                if key in counters and not owned & claimed:
                    total += 1
                    claimed |= owned
        return total
    all_forms = variant == "all_forms"
    return sum(
        row[c] for name in names for c in estimate_counters(PATTERNS_BY_NAME[name], all_forms)
    )


def estimate(
    rows: list,
    ranking: list,
    ks: tuple = ESTIMATE_KS,
    thresholds: tuple = ESTIMATE_THRESHOLDS,
    variant: str = "prudent",
) -> dict:
    """Frazione di campioni con ``n_sites_total + siti aggiunti ≥ soglia`` per i primi ``k``
    pattern della classifica (``k = 0``: siti attuali)."""
    ok = [r for r in rows if r.get("parse_ok")]
    out: dict = {}
    for k in (0, *ks):
        names = [name for name, _ in ranking[:k]]
        totals = [r["n_sites_total"] + added_sites(r, names, variant) for r in ok]
        out[k] = {
            "patterns": names,
            **{
                f"frac_ge_{th}": (sum(1 for t in totals if t >= th) / len(totals))
                if totals
                else float("nan")
                for th in thresholds
            },
        }
    return out
