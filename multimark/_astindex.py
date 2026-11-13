"""Indice dell'``ast`` condiviso da lettura, inserimento e rilevazione.

Riferimento: PIPELINE_metodo.md §3.1–3.2.

Tutto ciò che decide quali siti esistono e che valore hanno si calcola qui sopra, sull'``ast``
della libreria standard: spazi, a capo, commenti e parentesi ridondanti non esistono.

Contenuto:
- ``parse``: ``ast.parse(code, type_comments=False)``;
- visita in profondità esplicita in pre-ordine (``iter_child_nodes``), mai ``ast.walk``;
- unità di funzione (§3.2): la ``FunctionDef``/``AsyncFunctionDef`` più esterna che contiene il
  nodo, oppure l'unità fittizia ``MODULE``;
- posizione di ogni nodo nella lista del genitore (per le coppie di istruzioni consecutive);
- predicati ``kind``, ``is_pure``, ``is_numeric_constant`` di §3.3.1.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Optional

FUNCTION_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)

#: Indice dell'unità ``MODULE`` (viene dopo tutte le funzioni nell'ordine di §3.9).
MODULE_INDEX = -1


def parse(code: str) -> ast.Module:
    """Parser di lettura (§3.1). Solleva ``SyntaxError`` (o ``ValueError`` per byte nulli)."""
    return ast.parse(code, type_comments=False)


def iter_preorder(root: ast.AST) -> Iterator[ast.AST]:
    """Visita in profondità in pre-ordine, figli nell'ordine di ``ast.iter_child_nodes``."""
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(list(ast.iter_child_nodes(node))))


def count_params(fn: ast.AST) -> int:
    """``n_params`` di §3.2: ``len(posonlyargs) + len(args) + len(kwonlyargs)``."""
    assert isinstance(fn, FUNCTION_TYPES)
    a = fn.args
    return len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs)


@dataclass(frozen=True)
class FunctionUnit:
    """Unità di funzione di §3.2. ``index`` = ordine di visita (``MODULE_INDEX`` per ``MODULE``)."""

    index: int
    name: str
    n_params: int
    node: Optional[ast.AST] = field(default=None, compare=False, repr=False, hash=False)

    @property
    def fid(self) -> tuple[str, int]:
        """Identificatore ``(name, n_params)``; ``("", 0)`` per ``MODULE``."""
        return (self.name, self.n_params)

    @property
    def is_module(self) -> bool:
        return self.index == MODULE_INDEX

    @property
    def order_key(self) -> tuple[int, int]:
        """Ordine «funzioni in ordine di visita, poi ``MODULE``» (§3.9)."""
        return (1, 0) if self.is_module else (0, self.index)


MODULE_UNIT = FunctionUnit(MODULE_INDEX, "", 0, None)


@dataclass(frozen=True)
class Slot:
    """Dove sta un nodo nel genitore: campo e, se il campo è una lista, indice."""

    parent: Optional[ast.AST]
    field: str
    index: Optional[int]


class AstIndex:
    """Indice di un modulo: ordine di visita, genitori, unità di funzione."""

    def __init__(self, tree: ast.Module) -> None:
        self.tree = tree
        self.order: list[ast.AST] = []
        self.position: dict[int, int] = {}
        self.slots: dict[int, Slot] = {}
        self.units: dict[int, FunctionUnit] = {}
        self.functions: list[FunctionUnit] = []
        stack: list[tuple[ast.AST, Slot, FunctionUnit]] = [
            (tree, Slot(None, "", None), MODULE_UNIT)
        ]
        while stack:
            node, slot, unit = stack.pop()
            if unit.is_module and isinstance(node, FUNCTION_TYPES):
                unit = FunctionUnit(len(self.functions), node.name, count_params(node), node)
                self.functions.append(unit)
            self.position[id(node)] = len(self.order)
            self.order.append(node)
            self.slots[id(node)] = slot
            self.units[id(node)] = unit
            children: list[tuple[ast.AST, Slot, FunctionUnit]] = []
            for name, value in ast.iter_fields(node):
                if isinstance(value, ast.AST):
                    children.append((value, Slot(node, name, None), unit))
                elif isinstance(value, list):
                    for i, item in enumerate(value):
                        if isinstance(item, ast.AST):
                            children.append((item, Slot(node, name, i), unit))
            stack.extend(reversed(children))

    @classmethod
    def from_code(cls, code: str) -> AstIndex:
        return cls(parse(code))

    def unit_of(self, node: ast.AST) -> FunctionUnit:
        """``function_of(node)`` di §3.2."""
        return self.units[id(node)]

    def slot_of(self, node: ast.AST) -> Slot:
        return self.slots[id(node)]

    def parent_of(self, node: ast.AST) -> Optional[ast.AST]:
        return self.slots[id(node)].parent

    def next_sibling(self, node: ast.AST) -> Optional[ast.AST]:
        """Elemento successivo nella stessa lista del genitore (istruzione consecutiva)."""
        slot = self.slots[id(node)]
        if slot.parent is None or slot.index is None:
            return None
        items = getattr(slot.parent, slot.field)
        if slot.index + 1 < len(items):
            nxt = items[slot.index + 1]
            return nxt if isinstance(nxt, ast.AST) else None
        return None

    def nodes_of_unit(self, unit: FunctionUnit) -> Iterator[ast.AST]:
        """Nodi dell'unità in ordine di visita."""
        for node in self.order:
            if self.units[id(node)] == unit:
                yield node

    @property
    def all_units(self) -> list[FunctionUnit]:
        """Funzioni in ordine di visita, poi ``MODULE`` (§3.9)."""
        return [*self.functions, MODULE_UNIT]


# ---------------------------------------------------------------------- predicati di §3.3.1

_IMPURE_TYPES: tuple[type, ...] = (
    ast.Call,
    ast.Await,
    ast.Yield,
    ast.YieldFrom,
    ast.NamedExpr,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
)


def kind(expr: ast.AST) -> int:
    """Classe sintattica di un operando: Constant=0, Name=1, Attribute=2, Subscript=3, Call=4,
    BinOp/UnaryOp=5, altro=6."""
    if isinstance(expr, ast.Constant):
        return 0
    if isinstance(expr, ast.Name):
        return 1
    if isinstance(expr, ast.Attribute):
        return 2
    if isinstance(expr, ast.Subscript):
        return 3
    if isinstance(expr, ast.Call):
        return 4
    if isinstance(expr, (ast.BinOp, ast.UnaryOp)):
        return 5
    return 6


def is_pure(expr: ast.AST) -> bool:
    """«Puro» = non contiene ``Call``, ``Await``, ``Yield``, ``NamedExpr``, comprehension."""
    return not any(isinstance(n, _IMPURE_TYPES) for n in iter_preorder(expr))


def is_numeric_constant(expr: ast.AST) -> bool:
    """``Constant`` ``int``/``float``, non ``bool``, non complesso."""
    return (
        isinstance(expr, ast.Constant)
        and isinstance(expr.value, (int, float))
        and not isinstance(expr.value, bool)
    )


def is_none(expr: ast.AST) -> bool:
    return isinstance(expr, ast.Constant) and expr.value is None


def names_in(expr: ast.AST) -> set[str]:
    """Identificatori ``Name`` che compaiono in un'espressione."""
    return {n.id for n in iter_preorder(expr) if isinstance(n, ast.Name)}


def end_key(node: ast.AST) -> tuple[int, int]:
    """Posizione di fine di un nodo come coppia confrontabile."""
    return (getattr(node, "end_lineno", 0) or 0, getattr(node, "end_col_offset", 0) or 0)


def start_key(node: ast.AST) -> tuple[int, int]:
    return (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))


def module_bindings(tree: ast.AST) -> set[str]:
    """Nomi con almeno un binding nel modulo (qualsiasi scope): assegnazioni, ``del``, parametri,
    ``def``/``class``, ``import``, ``except ... as``, ``global``/``nonlocal``, pattern di
    ``match``."""
    out: set[str] = set()
    for node in iter_preorder(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            out.add(node.id)
        elif isinstance(node, ast.arg):
            out.add(node.arg)
        elif isinstance(node, (*FUNCTION_TYPES, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.alias):
            out.add(node.asname or node.name.split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            out.update(node.names)
        else:
            # Pattern di ``match`` (Python ≥ 3.10): ``MatchAs``/``MatchStar`` hanno ``name``,
            # ``MatchMapping`` ha ``rest``.
            for attr in ("name", "rest"):
                if type(node).__name__.startswith("Match"):
                    value = getattr(node, attr, None)
                    if isinstance(value, str):
                        out.add(value)
    return out
