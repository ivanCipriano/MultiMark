"""Gli 8 canali strutturali (PIPELINE_metodo.md §3.3, numerazione di MCSS Tabella 2, p. 5).

Per ogni canale: riconoscimento del sito sull'``ast``, lettura del valore (forma 0 o forma 1) e,
da P1, scrittura con LibCST. In P0 c'è solo il **riconoscimento** (``recognize``).

| # | canale          | forma 0                         | forma 1                         |
|---|-----------------|---------------------------------|---------------------------------|
| 1 | ``aug_assign``  | ``x = x op e``                  | ``x op= e``                     |
| 2 | ``compare_dir`` | operando di ``kind`` minore a sx | operando di ``kind`` minore a dx |
| 3 | ``equality_dir``| come 2 (``==``, ``!=``)          | come 2                          |
| 4 | ``list_comp``   | ``L = []`` + ciclo con append   | ``L = [expr for x in it]``      |
| 5 | ``ternary``     | ``if/else``                     | ``x = a if t else b``           |
| 6 | ``operand_order``| costante numerica a destra     | costante numerica a sinistra    |
| 7 | ``empty_coll``  | ``[]``, ``{}``                  | ``list()``, ``dict()``          |
| 8 | ``none_check``  | ``is None`` / ``is not None``   | ``== None`` / ``!= None``       |

**Condizioni.** Le condizioni di §3.3.1 sono applicate quando ``ReadOptions.guards`` è vero
(default). Con ``guards=False`` (solo per l'inventario, ``--no-guards``, §4.2 punto 6) si tolgono
le sole condizioni *semantiche* (purezza, insieme degli operatori e tipo dell'operando di
``aug_assign``, ``kind`` dell'altro operando di ``operand_order``, condizioni su ``L`` e ``x`` di
``list_comp``, ridefinizione di ``list``/``dict``); restano quelle che servono perché le due forme
siano definite e quelle di non interferenza qui sotto. TODO(ivan): confermare questo perimetro di
``--no-guards``.

**Non interferenza (§3.3.2 punto 3).** Oltre alla regola «un nodo appartiene al più a un sito, vince
il canale con numero minore» (applicata in ``sites.py`` con gli insiemi ``owned``), alcune
condizioni sono scritte in modo da valere **in entrambe le forme**, perché cambiare la forma di un
sito non crei né distrugga siti di altri canali:

- ``operand_order``: non è un sito il ``BinOp`` valore di ``x = …`` che in una delle due forme
  sarebbe ``x = x op e`` di ``aug_assign`` (``x = 1 + x`` ↔ ``x = x + 1``);
- ``ternary``: non è un sito se un ramo ``x = a`` sarebbe un sito di ``aug_assign`` (in qualsiasi
  orientamento degli operandi), se ``a`` o ``b`` è un ``IfExp`` (la forma 0 creerebbe un secondo
  sito ``ternary``), o se l'istruzione è l'unico elemento dell'``orelse`` di un ``If`` (``elif``:
  la condizione si controlla anche sulla forma 1, perché la forma 0 sarebbe un ``elif``);
- ``empty_coll``: non è un sito il ``list()`` di ``L = list()`` seguito da un ciclo che, con
  ``L = []``, sarebbe un sito ``list_comp``.
- (canale dei nomi, ``names.py``) il bersaglio del ciclo di un sito ``list_comp`` in forma 0 non è
  un binding, come la variabile di una comprehension.

Queste regole sono interpretazioni di §3.3.2 (TODO(ivan): confermare).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Callable, Optional

from multimark._astindex import (
    AstIndex,
    end_key,
    is_none,
    is_numeric_constant,
    is_pure,
    kind,
    module_bindings,
    names_in,
    start_key,
)

CHANNELS: tuple[str, ...] = (
    "aug_assign",
    "compare_dir",
    "equality_dir",
    "list_comp",
    "ternary",
    "operand_order",
    "empty_coll",
    "none_check",
)
CHANNEL_NUMBER: dict[str, int] = {c: i + 1 for i, c in enumerate(CHANNELS)}

CANONICAL_MODES = ("kind", "paper")


@dataclass(frozen=True)
class ReadOptions:
    """Opzioni di lettura.

    - ``canonical``: ``"kind"`` (2D, base di ``multimark``: se ``kind(sx) = kind(dx)`` il nodo non
      è un sito) oppure ``"paper"`` (``mcss``, §4.2 punto 3: a parità di ``kind``, ordine
      lessicografico del testo ``ast.unparse`` dell'operando; testi uguali → nessun sito).
    - ``guards``: condizioni semantiche di §3.3.1 (vedi docstring del modulo).
    """

    canonical: str = "kind"
    guards: bool = True

    def __post_init__(self) -> None:
        if self.canonical not in CANONICAL_MODES:
            raise ValueError(f"canonical must be one of {CANONICAL_MODES}: {self.canonical!r}")


@dataclass(frozen=True)
class Match:
    """Un sito riconosciuto: canale, nodo radice, valore letto e nodi che gli appartengono."""

    channel: str
    node: ast.AST
    value: int
    owned: frozenset[int]


class ReadContext:
    """Dati di modulo calcolati una volta per la lettura (indice, binding, letture dei nomi)."""

    def __init__(self, index: AstIndex, options: ReadOptions) -> None:
        self.index = index
        self.options = options
        self.bound = module_bindings(index.tree)
        # Letture ``Name`` per (unità, nome), con posizione d'inizio (``list_comp``).
        self.loads: dict[tuple[int, str], list[tuple[int, int]]] = {}
        for node in index.order:
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                key = (index.unit_of(node).index, node.id)
                self.loads.setdefault(key, []).append(start_key(node))

    @property
    def guards(self) -> bool:
        return self.options.guards


def _ids(*nodes: ast.AST) -> frozenset[int]:
    return frozenset(id(n) for n in nodes)


# ---------------------------------------------------------------------- 1. aug_assign

_AUG_GUARDED_CONST_OPS = (ast.Add, ast.Sub)
_AUG_GUARDED_PURE_OPS = (ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)


def _aug_condition(op: ast.operator, e: ast.AST, ctx: ReadContext) -> bool:
    """``op ∈ {+, -}`` con ``e`` costante numerica, oppure ``op ∈ {/, //, %, **}`` con ``e`` puro.
    Senza condizioni: qualsiasi operatore binario e qualsiasi ``e``."""
    if not ctx.guards:
        return True
    if isinstance(op, _AUG_GUARDED_CONST_OPS):
        return is_numeric_constant(e)
    if isinstance(op, _AUG_GUARDED_PURE_OPS):
        return is_pure(e)
    return False


def _would_be_aug(target: str, value: ast.AST, ctx: ReadContext) -> bool:
    """``x = value`` è (o, invertendo gli operandi di ``operand_order``, sarebbe) un sito 1."""
    if not isinstance(value, ast.BinOp):
        return False
    left, right = value.left, value.right
    if isinstance(left, ast.Name) and left.id == target and _aug_condition(value.op, right, ctx):
        return True
    return (
        isinstance(value.op, (ast.Add, ast.Mult))
        and isinstance(right, ast.Name)
        and right.id == target
        and is_numeric_constant(left)
        and _aug_condition(value.op, left, ctx)
    )


def _single_name_target(node: ast.Assign) -> Optional[ast.Name]:
    if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0]
    return None


def recognize_aug_assign(node: ast.AST, ctx: ReadContext) -> Optional[Match]:
    """Canale 1: ``x = x op e`` (forma 0) o ``x op= e`` (forma 1)."""
    if isinstance(node, ast.Assign):
        target = _single_name_target(node)
        value = node.value
        if (
            target is not None
            and isinstance(value, ast.BinOp)
            and isinstance(value.left, ast.Name)
            and value.left.id == target.id
            and _aug_condition(value.op, value.right, ctx)
        ):
            return Match("aug_assign", node, 0, _ids(node, target, value, value.left))
    elif isinstance(node, ast.AugAssign):
        if isinstance(node.target, ast.Name) and _aug_condition(node.op, node.value, ctx):
            return Match("aug_assign", node, 1, _ids(node, node.target))
    return None


# ---------------------------------------------------- 2, 3. compare_dir, equality_dir

_ORDER_OPS = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)
_EQUALITY_OPS = (ast.Eq, ast.NotEq)


def _is_none_or_bool(expr: ast.AST) -> bool:
    return isinstance(expr, ast.Constant) and (expr.value is None or isinstance(expr.value, bool))


def _direction(left: ast.AST, right: ast.AST, ctx: ReadContext) -> Optional[int]:
    """0 se l'operando «minore» è a sinistra, 1 se è a destra, ``None`` se non c'è forma
    canonica."""
    kl, kr = kind(left), kind(right)
    if kl != kr:
        return 0 if kl < kr else 1
    if ctx.options.canonical == "kind":
        return None
    tl, tr = ast.unparse(left), ast.unparse(right)
    if tl == tr:
        return None
    return 0 if tl < tr else 1


def _recognize_compare(
    node: ast.AST, ctx: ReadContext, channel: str, ops: tuple[type, ...]
) -> Optional[Match]:
    if not (isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ops)):
        return None
    left, right = node.left, node.comparators[0]
    if isinstance(left, ast.Compare) or isinstance(right, ast.Compare):
        return None
    if channel == "equality_dir" and (_is_none_or_bool(left) or _is_none_or_bool(right)):
        return None
    if ctx.guards and not (is_pure(left) or is_pure(right)):
        return None
    value = _direction(left, right, ctx)
    if value is None:
        return None
    return Match(channel, node, value, _ids(node))


def recognize_compare_dir(node: ast.AST, ctx: ReadContext) -> Optional[Match]:
    """Canale 2: ``Compare`` con un solo operatore in ``{<, <=, >, >=}``."""
    return _recognize_compare(node, ctx, "compare_dir", _ORDER_OPS)


def recognize_equality_dir(node: ast.AST, ctx: ReadContext) -> Optional[Match]:
    """Canale 3: ``Compare`` con un solo operatore in ``{==, !=}``, senza ``None``, ``True``,
    ``False``."""
    return _recognize_compare(node, ctx, "equality_dir", _EQUALITY_OPS)


# ---------------------------------------------------------------------- 4. list_comp


def _is_empty_list(expr: ast.AST) -> bool:
    return isinstance(expr, ast.List) and not expr.elts and isinstance(expr.ctx, ast.Load)


def _is_empty_call(expr: ast.AST, name: str) -> bool:
    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Name)
        and expr.func.id == name
        and not expr.args
        and not expr.keywords
    )


def _loop_append(loop: ast.AST, list_name: str) -> Optional[tuple[ast.Name, ast.AST, ast.Expr]]:
    """``for x in it: L.append(expr)`` (una sola istruzione, nessun ``else``).

    Restituisce ``(x, expr, stmt)`` o ``None``."""
    if type(loop) is not ast.For or loop.orelse or len(loop.body) != 1:
        return None
    if not isinstance(loop.target, ast.Name):
        return None
    stmt = loop.body[0]
    if not isinstance(stmt, ast.Expr):
        return None
    call = stmt.value
    if not (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "append"
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == list_name
        and len(call.args) == 1
        and not isinstance(call.args[0], ast.Starred)
        and not call.keywords
    ):
        return None
    return loop.target, call.args[0], stmt


def _list_comp_conditions(
    list_name: str, var: str, expr: ast.AST, it: ast.AST, last: ast.AST, ctx: ReadContext
) -> bool:
    """Condizioni di §3.3.1 riga 4 su ``L``, ``x``, ``expr``, ``it``.

    «``expr`` e ``it`` puri rispetto a ``L``» è letto come «``L`` non compare in ``expr`` né in
    ``it``» (TODO(ivan): confermare; la lettura «puri» in senso stretto escluderebbe ogni
    ``range(n)``). «``x`` non è letto dopo il ciclo»: nessuna lettura ``Name(x)`` nella stessa unità
    che inizi dopo la fine del sito (TODO(ivan): una lettura *prima* del ciclo dentro un ciclo
    esterno non è esclusa)."""
    if var == list_name:
        return False
    if not ctx.guards:
        return True
    if var in names_in(it) or list_name in names_in(expr) or list_name in names_in(it):
        return False
    unit = ctx.index.unit_of(last)
    end = end_key(last)
    return not any(pos > end for pos in ctx.loads.get((unit.index, var), []))


def list_comp_loop_form(
    assign: ast.AST, ctx: ReadContext, allow_list_call: bool = False
) -> Optional[Match]:
    """Coppia ``L = []`` ; ``for x in it: L.append(expr)`` (forma 0) radicata in ``assign``.

    Con ``allow_list_call=True`` accetta anche ``L = list()`` (serve solo alla regola di non
    interferenza di ``empty_coll``)."""
    if not isinstance(assign, ast.Assign):
        return None
    target = _single_name_target(assign)
    if target is None:
        return None
    if not (
        _is_empty_list(assign.value) or (allow_list_call and _is_empty_call(assign.value, "list"))
    ):
        return None
    loop = ctx.index.next_sibling(assign)
    if loop is None:
        return None
    found = _loop_append(loop, target.id)
    if found is None:
        return None
    var, expr, stmt = found
    assert isinstance(loop, ast.For)
    if not _list_comp_conditions(target.id, var.id, expr, loop.iter, loop, ctx):
        return None
    call = stmt.value
    assert isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
    owned = _ids(assign, target, assign.value, loop, var, stmt, call, call.func, call.func.value)
    return Match("list_comp", assign, 0, owned)


def recognize_list_comp(node: ast.AST, ctx: ReadContext) -> Optional[Match]:
    """Canale 4: coppia ``L = []`` + ciclo con ``append`` (forma 0) o ``L = [expr for x in it]``
    con una sola clausola e nessun ``if`` (forma 1)."""
    if not isinstance(node, ast.Assign):
        return None
    loop_form = list_comp_loop_form(node, ctx)
    if loop_form is not None:
        return loop_form
    target = _single_name_target(node)
    comp = node.value
    if target is None or not isinstance(comp, ast.ListComp) or len(comp.generators) != 1:
        return None
    gen = comp.generators[0]
    if gen.ifs or gen.is_async or not isinstance(gen.target, ast.Name):
        return None
    if not _list_comp_conditions(target.id, gen.target.id, comp.elt, gen.iter, node, ctx):
        return None
    return Match("list_comp", node, 1, _ids(node, target, comp, gen, gen.target))


# ---------------------------------------------------------------------- 5. ternary


def _is_elif_position(stmt: ast.AST, ctx: ReadContext) -> bool:
    """L'istruzione è l'unico elemento dell'``orelse`` di un ``If`` (``elif`` o ``else: if``)."""
    slot = ctx.index.slot_of(stmt)
    parent = slot.parent
    return isinstance(parent, ast.If) and slot.field == "orelse" and len(parent.orelse) == 1


def _ternary_ok(var: str, a: ast.AST, b: ast.AST, ctx: ReadContext) -> bool:
    if isinstance(a, ast.IfExp) or isinstance(b, ast.IfExp):
        return False
    if _would_be_aug(var, a, ctx) or _would_be_aug(var, b, ctx):
        return False
    return not ctx.guards or (is_pure(a) and is_pure(b))


def recognize_ternary(node: ast.AST, ctx: ReadContext) -> Optional[Match]:
    """Canale 5: ``if t: x = a else: x = b`` (forma 0) o ``x = a if t else b`` (forma 1)."""
    if isinstance(node, ast.If):
        if len(node.body) != 1 or len(node.orelse) != 1:
            return None
        s0, s1 = node.body[0], node.orelse[0]
        if not (isinstance(s0, ast.Assign) and isinstance(s1, ast.Assign)):
            return None
        t0, t1 = _single_name_target(s0), _single_name_target(s1)
        if t0 is None or t1 is None or t0.id != t1.id or _is_elif_position(node, ctx):
            return None
        if not _ternary_ok(t0.id, s0.value, s1.value, ctx):
            return None
        return Match("ternary", node, 0, _ids(node, s0, s1, t0, t1))
    if isinstance(node, ast.Assign) and isinstance(node.value, ast.IfExp):
        target = _single_name_target(node)
        if target is None or _is_elif_position(node, ctx):
            return None
        exp = node.value
        if not _ternary_ok(target.id, exp.body, exp.orelse, ctx):
            return None
        return Match("ternary", node, 1, _ids(node, target, exp))
    return None


# ---------------------------------------------------------------------- 6. operand_order


def recognize_operand_order(node: ast.AST, ctx: ReadContext) -> Optional[Match]:
    """Canale 6: ``BinOp`` con ``op ∈ {+, *}``, una costante numerica e un ``Name``/``Attribute``/
    ``Subscript``; forma 0 = costante a destra."""
    if not (isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mult))):
        return None
    lc, rc = is_numeric_constant(node.left), is_numeric_constant(node.right)
    if lc == rc:
        return None
    other = node.left if rc else node.right
    if ctx.guards:
        if kind(other) not in (1, 2, 3):
            return None
    elif isinstance(other, ast.Constant) or (
        isinstance(other, ast.BinOp) and type(other.op) is type(node.op)
    ):
        return None
    parent = ctx.index.parent_of(node)
    if isinstance(parent, ast.BinOp) and type(parent.op) is type(node.op):
        return None
    if isinstance(parent, ast.Assign) and parent.value is node:
        target = _single_name_target(parent)
        if target is not None and _would_be_aug(target.id, node, ctx):
            return None
    return Match("operand_order", node, 0 if rc else 1, _ids(node))


# ---------------------------------------------------------------------- 7. empty_coll


def recognize_empty_coll(node: ast.AST, ctx: ReadContext) -> Optional[Match]:
    """Canale 7: ``[]``/``{}`` (forma 0) o ``list()``/``dict()`` (forma 1)."""
    if _is_empty_list(node) or (isinstance(node, ast.Dict) and not node.keys):
        return Match("empty_coll", node, 0, _ids(node))
    for name in ("list", "dict"):
        if _is_empty_call(node, name):
            if ctx.guards and name in ctx.bound:
                return None
            parent = ctx.index.parent_of(node)
            if (
                name == "list"
                and isinstance(parent, ast.Assign)
                and parent.value is node
                and list_comp_loop_form(parent, ctx, allow_list_call=True) is not None
            ):
                return None
            assert isinstance(node, ast.Call)
            return Match("empty_coll", node, 1, _ids(node, node.func))
    return None


# ---------------------------------------------------------------------- 8. none_check

_NONE_OPS = (ast.Eq, ast.NotEq, ast.Is, ast.IsNot)


def recognize_none_check(node: ast.AST, ctx: ReadContext) -> Optional[Match]:
    """Canale 8: ``x is None``/``x is not None`` (forma 0) o ``x == None``/``x != None``
    (forma 1)."""
    if not (
        isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], _NONE_OPS)
        and is_none(node.comparators[0])
    ):
        return None
    if ctx.guards and not is_pure(node.left):
        return None
    value = 0 if isinstance(node.ops[0], (ast.Is, ast.IsNot)) else 1
    return Match("none_check", node, value, _ids(node))


# ---------------------------------------------------------------------- tabella

Recognizer = Callable[[ast.AST, ReadContext], Optional[Match]]

RECOGNIZERS: dict[str, Recognizer] = {
    "aug_assign": recognize_aug_assign,
    "compare_dir": recognize_compare_dir,
    "equality_dir": recognize_equality_dir,
    "list_comp": recognize_list_comp,
    "ternary": recognize_ternary,
    "operand_order": recognize_operand_order,
    "empty_coll": recognize_empty_coll,
    "none_check": recognize_none_check,
}


def recognize(node: ast.AST, ctx: ReadContext) -> list[Match]:
    """Candidati di tutti i canali radicati in ``node``, nell'ordine dei canali."""
    out: list[Match] = []
    for channel in CHANNELS:
        match = RECOGNIZERS[channel](node, ctx)
        if match is not None:
            out.append(match)
    return out


# ---------------------------------------------------------------------- scrittura (P1)


def write_form(code: str, matches: list[Match], forms: dict[int, int]) -> str:
    """Scrive con LibCST la forma richiesta dei siti (§3.3.3). Arriva in P1."""
    raise NotImplementedError("P1: scrittura dei canali con LibCST (§3.3.3)")
