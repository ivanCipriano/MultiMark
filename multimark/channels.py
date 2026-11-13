"""Gli 8 canali strutturali (PIPELINE_metodo.md §3.3, numerazione di MCSS Tabella 2, p. 5).

Per ogni canale: riconoscimento del sito sull'``ast``, lettura del valore (forma 0 o forma 1) e,
scrittura con LibCST (``multimark/rewrite.py``).

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
| 9 | ``range_zero``  | ``range(0, n)``                 | ``range(n)``                    |
| 10| ``slice_lower`` | ``a[0:n]``, ``a[0:]``           | ``a[:n]``, ``a[:]``             |
| 11| ``else_return`` | ``if c: …return`` + ``else: Y`` | ``if c: …return`` + ``Y`` dopo  |
| 12| ``nested_if``   | ``if a: if b:``                 | ``if a and b:``                 |
| 13| ``square``      | ``x * x``                       | ``x ** 2``                      |
| 14| ``return_none`` | ``return None``                 | ``return``                      |

I canali 9–14 (§3.3.1b [v1.2]) sono solo di ``multimark`` (``channels="extended"``); ``mcss`` usa
1–8 (``channels="mcss8"``). Per la regola «vince il canale con numero minore» i canali di MCSS
prevalgono sempre sui nuovi.

**Condizioni.** Le condizioni di §3.3.1 sono applicate quando ``ReadOptions.guards`` è vero
(default). Con ``guards=False`` (solo per l'inventario, ``--no-guards``, §4.2 punto 6) si tolgono
le sole condizioni *semantiche* (purezza, insieme degli operatori e tipo dell'operando di
``aug_assign``, ``kind`` dell'altro operando di ``operand_order``, condizioni su ``L`` e ``x`` di
``list_comp``, ridefinizione di ``list``/``dict``); restano quelle che servono perché le due forme
siano definite e quelle di non interferenza qui sotto (perimetro confermato da Ivan, 13 novembre
2026).

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

Queste regole applicano §3.3.2 e sono confermate da Ivan (13 novembre 2026; MD10 di
``docs/mcss_deviations.md``).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Callable, Optional

from multimark._astindex import (
    AstIndex,
    is_none,
    is_numeric_constant,
    is_pure,
    iter_preorder,
    kind,
    module_bindings,
    names_in,
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
    "range_zero",
    "slice_lower",
    "else_return",
    "nested_if",
    "square",
    "return_none",
)
CHANNEL_NUMBER: dict[str, int] = {c: i + 1 for i, c in enumerate(CHANNELS)}

#: Insiemi di canali dell'opzione ``channels`` (§3.11 [v1.2]): ``mcss8`` = 1–8 (MCSS),
#: ``extended`` = 1–14 (base di ``multimark``). ``extended+str`` (canale 15, decisione P di §7) non
#: è ancora implementato.
CHANNEL_SETS: dict[str, tuple[str, ...]] = {"mcss8": CHANNELS[:8], "extended": CHANNELS}
CHANNEL_SET_NAMES = ("mcss8", "extended", "extended+str")

CANONICAL_MODES = ("kind", "paper")


@dataclass(frozen=True)
class ReadOptions:
    """Opzioni di lettura.

    - ``canonical``: ``"kind"`` (2D, base di ``multimark``: se ``kind(sx) = kind(dx)`` il nodo non
      è un sito) oppure ``"paper"`` (``mcss``, §4.2 punto 3: a parità di ``kind``, ordine
      lessicografico del testo ``ast.unparse`` dell'operando; testi uguali → nessun sito).
    - ``guards``: condizioni semantiche di §3.3.1 (vedi docstring del modulo).
    - ``channels``: ``"extended"`` (canali 1–14, base di ``multimark``) o ``"mcss8"`` (1–8).
    """

    canonical: str = "kind"
    guards: bool = True
    channels: str = "extended"

    def __post_init__(self) -> None:
        if self.canonical not in CANONICAL_MODES:
            raise ValueError(f"canonical must be one of {CANONICAL_MODES}: {self.canonical!r}")
        if self.channels not in CHANNEL_SET_NAMES:
            raise ValueError(f"channels must be one of {CHANNEL_SET_NAMES}: {self.channels!r}")
        if self.channels not in CHANNEL_SETS:
            # TODO(ivan): canale 15 (str_method con guardia) solo dopo la decisione P di §7.
            raise NotImplementedError("channels=extended+str: channel 15 is not implemented yet")

    @property
    def active(self) -> tuple[str, ...]:
        return CHANNEL_SETS[self.channels]


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
        # Riferimenti ``Name`` che non sono binding (``Load``, ``Del``) per (unità, nome): servono
        # alla condizione su ``x`` di ``list_comp``.
        self.references: dict[tuple[int, str], list[int]] = {}
        for node in index.order:
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Load, ast.Del)):
                key = (index.unit_of(node).index, node.id)
                self.references.setdefault(key, []).append(id(node))
        # Nodi dentro una f-string: non sono mai siti (§3.1, «un nodo dentro una stringa non è
        # mai un sito»; inoltre le posizioni ``ast`` dentro le f-string non sono affidabili prima
        # di Python 3.12, e la scrittura ritrova i nodi per posizione).
        self.in_fstring: set[int] = set()
        for node in index.order:
            if isinstance(node, ast.JoinedStr):
                self.in_fstring.update(id(n) for n in iter_preorder(node))

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
    list_name: str,
    var: str,
    expr: ast.AST,
    it: ast.AST,
    site_stmts: tuple[ast.AST, ...],
    ctx: ReadContext,
) -> bool:
    """Condizioni di §3.3.1 riga 4 su ``L``, ``x``, ``expr``, ``it`` (decisioni di Ivan del 13
    novembre 2026, MD12):

    - «``expr`` e ``it`` puri rispetto a ``L``» significa esattamente «``L`` non compare in
      ``expr`` né in ``it``»; nessun requisito di purezza (``range(n)`` va bene);
    - ``x`` non compare in ``it``;
    - «``x`` non letto dopo il ciclo», in forma stretta: nella funzione ``x`` non ha **nessun**
      riferimento (lettura o ``del``) fuori dalle istruzioni del sito, né prima né dopo né in cicli
      esterni; sono ammessi solo altri binding di ``x`` come bersaglio. Una lettura «prima» dentro
      un ciclo esterno è una lettura dopo nel tempo, e nella forma comprehension ``x`` non sarebbe
      definita."""
    if var == list_name:
        return False
    if not ctx.guards:
        return True
    if var in names_in(it) or list_name in names_in(expr) or list_name in names_in(it):
        return False
    unit = ctx.index.unit_of(site_stmts[0])
    inside = {id(n) for stmt in site_stmts for n in iter_preorder(stmt)}
    return all(ref in inside for ref in ctx.references.get((unit.index, var), []))


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
    if not _list_comp_conditions(target.id, var.id, expr, loop.iter, (assign, loop), ctx):
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
    if not _list_comp_conditions(target.id, gen.target.id, comp.elt, gen.iter, (node,), ctx):
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


# ---------------------------------------------------------------------- 9. range_zero


def _int_const(expr: ast.AST, value: int) -> bool:
    return (
        isinstance(expr, ast.Constant)
        and type(expr.value) is int  # non bool
        and expr.value == value
    )


def recognize_range_zero(node: ast.AST, ctx: ReadContext) -> Optional[Match]:
    """Canale 9: ``range(0, n)`` (forma 0) o ``range(n)`` (forma 1), §3.3.1b."""
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "range"
        and not node.keywords
        and 1 <= len(node.args) <= 2
        and not any(isinstance(a, ast.Starred) for a in node.args)
    ):
        return None
    if ctx.guards and "range" in ctx.bound:
        return None
    if len(node.args) == 2:
        if not _int_const(node.args[0], 0):
            return None
        return Match("range_zero", node, 0, _ids(node, node.func, node.args[0]))
    return Match("range_zero", node, 1, _ids(node, node.func))


# ---------------------------------------------------------------------- 10. slice_lower


def recognize_slice_lower(node: ast.AST, ctx: ReadContext) -> Optional[Match]:
    """Canale 10: ``a[0:n]``, ``a[0:]`` (forma 0) o ``a[:n]``, ``a[:]`` (forma 1), §3.3.1b."""
    if not (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice)):
        return None
    sl = node.slice
    if sl.step is not None:
        return None
    if sl.lower is None:
        return Match("slice_lower", node, 1, _ids(node, sl))
    if _int_const(sl.lower, 0):
        return Match("slice_lower", node, 0, _ids(node, sl, sl.lower))
    return None


# ---------------------------------------------------------------------- 11. else_return

_TERMINATORS = (ast.Return, ast.Raise, ast.Continue, ast.Break)


def _block_of(stmt: ast.AST, ctx: ReadContext) -> Optional[tuple[list, int]]:
    """Lista di istruzioni che contiene ``stmt`` e posizione di ``stmt`` in essa."""
    slot = ctx.index.slot_of(stmt)
    if slot.parent is None or slot.index is None:
        return None
    items = getattr(slot.parent, slot.field)
    if not isinstance(items, list) or not all(isinstance(x, ast.stmt) for x in items):
        return None
    return items, slot.index


def _is_assign_ifexp(stmt: ast.AST) -> bool:
    return isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.IfExp)


def _else_return_form1_shape(node: ast.If, body: list, ctx: ReadContext) -> bool:
    """``node`` (senza ``orelse``, corpo ``body``) avrebbe la forma 1 di ``else_return``."""
    if not body or not isinstance(body[-1], _TERMINATORS) or _is_elif_position(node, ctx):
        return False
    where = _block_of(node, ctx)
    if where is None:
        return False
    items, i = where
    if i == len(items) - 1 or isinstance(items[i + 1], ast.If):
        return False
    moved = items[i + 1 :]
    return not (len(moved) == 1 and _is_assign_ifexp(moved[0]))


def recognize_else_return(node: ast.AST, ctx: ReadContext) -> Optional[Match]:
    """Canale 11: ``if c: …; return X`` + ``else: Y…`` (forma 0) o + ``Y…`` dopo l'``if`` nello
    stesso blocco (forma 1), §3.3.1b.

    Oltre alle condizioni della pipeline (corpo che termina con ``return``/``raise``/``continue``/
    ``break``; forma 0: ``orelse[0]`` non è un ``If``; forma 1: l'``if`` non è l'ultima istruzione e
    la successiva non è un ``If``), per la non interferenza (§3.3.2 punto 3, MD15):

    - forma 0: l'``if`` è l'**ultima** istruzione del suo blocco, così le due scritture sono una
      l'inversa dell'altra (1→0 sposta in ``else`` *tutte* le istruzioni successive) e non nascono
      coppie ``list_comp`` fra la fine dell'``else`` e ciò che segue;
    - le istruzioni spostate non sono una sola assegnazione con ``IfExp`` (da sola nell'``else``
      sarebbe in posizione di ``elif`` e il sito ``ternary`` sparirebbe);
    - l'``if`` non è a sua volta un ``elif``.
    """
    if not isinstance(node, ast.If) or _is_elif_position(node, ctx):
        return None
    if not node.body or not isinstance(node.body[-1], _TERMINATORS):
        return None
    where = _block_of(node, ctx)
    if where is None:
        return None
    items, i = where
    if node.orelse:
        if isinstance(node.orelse[0], ast.If) or i != len(items) - 1:
            return None
        if len(node.orelse) == 1 and _is_assign_ifexp(node.orelse[0]):
            return None
        return Match("else_return", node, 0, _ids(node))
    if not _else_return_form1_shape(node, node.body, ctx):
        return None
    return Match("else_return", node, 1, _ids(node))


# ---------------------------------------------------------------------- 12. nested_if


def _sole_body_of_if_without_else(stmt: ast.AST, ctx: ReadContext) -> bool:
    slot = ctx.index.slot_of(stmt)
    parent = slot.parent
    return (
        isinstance(parent, ast.If)
        and slot.field == "body"
        and len(parent.body) == 1
        and not parent.orelse
    )


def _single_if(body: list) -> bool:
    return len(body) == 1 and isinstance(body[0], ast.If)


def recognize_nested_if(node: ast.AST, ctx: ReadContext) -> Optional[Match]:
    """Canale 12: ``if a: if b: corpo`` (forma 0) o ``if a and b: corpo`` (forma 1), §3.3.1b.

    Per la non interferenza (§3.3.2 punto 3, MD15) il sito si esclude anche quando, nella forma 1,
    l'``if`` sarebbe un sito ``else_return`` (corpo che termina con ``return`` & co. e istruzioni
    dopo l'``if``): ``else_return`` (11) vince su ``nested_if`` (12) solo in quella forma."""
    if not isinstance(node, ast.If) or node.orelse:
        return None
    if _sole_body_of_if_without_else(node, ctx):
        return None
    if _single_if(node.body):
        inner = node.body[0]
        assert isinstance(inner, ast.If)
        if inner.orelse or _single_if(inner.body):
            return None
        body, value, owned = inner.body, 0, _ids(node, inner)
    elif isinstance(node.test, ast.BoolOp) and isinstance(node.test.op, ast.And):
        body, value, owned = node.body, 1, _ids(node, node.test)
    else:
        return None
    if _else_return_form1_shape(node, body, ctx):
        return None
    return Match("nested_if", node, value, owned)


# ---------------------------------------------------------------------- 13. square


def recognize_square(node: ast.AST, ctx: ReadContext) -> Optional[Match]:
    """Canale 13: ``x * x`` (forma 0) o ``x ** 2`` (forma 1), §3.3.1b.

    ``x`` è ``Name`` o ``Attribute`` (puro); il ``BinOp`` non è figlio di un ``BinOp(Mult)``. Per
    la non interferenza (MD15) non è un sito il valore di ``x = x * x`` / ``x = x ** 2`` (la forma
    ``**`` sarebbe un sito ``aug_assign``)."""
    if not isinstance(node, ast.BinOp):
        return None
    base = node.left
    if not isinstance(base, (ast.Name, ast.Attribute)) or not is_pure(base):
        return None
    if isinstance(node.op, ast.Mult) and ast.dump(node.right) == ast.dump(base):
        value = 0
    elif isinstance(node.op, ast.Pow) and _int_const(node.right, 2):
        value = 1
    else:
        return None
    parent = ctx.index.parent_of(node)
    if isinstance(parent, ast.BinOp) and isinstance(parent.op, ast.Mult):
        return None
    if isinstance(parent, ast.Assign) and parent.value is node and isinstance(base, ast.Name):
        target = _single_name_target(parent)
        if target is not None and target.id == base.id:
            return None
    return Match("square", node, value, _ids(node))


# ---------------------------------------------------------------------- 14. return_none


def recognize_return_none(node: ast.AST, ctx: ReadContext) -> Optional[Match]:
    """Canale 14: ``return None`` (forma 0) o ``return`` (forma 1), §3.3.1b."""
    if not isinstance(node, ast.Return):
        return None
    if node.value is None:
        return Match("return_none", node, 1, _ids(node))
    if is_none(node.value):
        return Match("return_none", node, 0, _ids(node, node.value))
    return None


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
    "range_zero": recognize_range_zero,
    "slice_lower": recognize_slice_lower,
    "else_return": recognize_else_return,
    "nested_if": recognize_nested_if,
    "square": recognize_square,
    "return_none": recognize_return_none,
}


def recognize(node: ast.AST, ctx: ReadContext) -> list[Match]:
    """Candidati dei canali attivi radicati in ``node``, nell'ordine dei canali."""
    if id(node) in ctx.in_fstring:
        return []
    out: list[Match] = []
    for channel in ctx.options.active:
        match = RECOGNIZERS[channel](node, ctx)
        if match is not None:
            out.append(match)
    return out


# ---------------------------------------------------------------------- scrittura (P1)


def write_form(code: str, matches: list[Match], forms: dict[int, int]) -> str:
    """Scrive con LibCST la forma richiesta dei siti (§3.3.3). Arriva in P1."""
    raise NotImplementedError("P1: scrittura dei canali con LibCST (§3.3.3)")
