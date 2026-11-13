"""Canale dei nomi (PIPELINE_metodo.md §3.6, §4.3).

In P0 c'è solo la regola comune che dice **quali variabili sono siti** (§3.6.1), usata
dall'inventario (``n_vars``). Normalizzazione, lettura V1/V1b/V2/V2b, proponenti e rinomina
arrivano in P1 (``StaticProposer``) e P3 (``NeuralProposer`` in ``names_neural.py``).

Regola di §3.6.1: un sito è un nome ``n`` che, nella funzione ``f`` (unità di §3.2, quindi
comprese le funzioni annidate):

(a) ha almeno un binding come variabile locale (``Assign``, ``AugAssign``, ``AnnAssign``, bersaglio
    di ``For``, ``with ... as``, ``NamedExpr``; le comprehension **escluse**);
(b) non è parametro di ``f`` (salvo ``include_params=True``: allora i parametri contano come
    binding);
(c) ``len(n) ≥ 2`` e ``n`` non è ``_`` né inizia per ``_``;
(d) non è dichiarato ``global``/``nonlocal`` (in tutto il modulo, come T1.4);
(e) non compare come argomento con nome in una chiamata (``g(n=…)``) né come attributo (``.n``)
    (in tutto il modulo, come T1.4);
(f) ``f`` non usa ``locals``, ``vars``, ``eval``, ``exec``;
(g) ``n`` non è ``self``, ``cls``.

Fuori dalle funzioni (``MODULE``) i siti dei nomi esistono solo con ``module_level=True``
(opzione ``names.module_level``, [v1.2]; regole (h)–(i) in ``name_sites``).

Allineamento con T1.4 del benchmark (``attacks/t1/rename.py``, che accetta solo gruppi «fatti di
nomi e parametri»): un nome che nella funzione ha anche un binding non di variabile (``import``,
``def``, ``class``, ``except ... as``, pattern di ``match``) non è un sito.

Non interferenza con ``list_comp`` (§3.3.2 punto 3): il bersaglio del ciclo di un sito
``list_comp`` in forma 0 non conta come binding (nella forma 1 è la variabile di una comprehension,
esclusa da (a)); gli id di quei nodi arrivano in ``excluded_binding_ids``.

Rango: ordine di visita della **prima** occorrenza di binding del nome nella funzione (§3.4).
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Optional, Protocol

from multimark._astindex import FUNCTION_TYPES, AstIndex, FunctionUnit, iter_preorder

NAME_VARIANTS = ("V0", "V1", "V1b", "V2", "V2b")
_DYNAMIC_SCOPE = frozenset({"locals", "vars", "eval", "exec"})
_EXCLUDED_NAMES = frozenset({"self", "cls"})


@dataclass(frozen=True)
class NameSite:
    """Variabile sito del canale dei nomi: unità, nome, rango e posizione del primo binding."""

    unit: FunctionUnit
    name: str
    rank: int
    lineno: int
    col_offset: int

    @property
    def key(self) -> tuple[str, int, str, int]:
        return (self.unit.name, self.unit.n_params, "names", self.rank)

    @property
    def dup_index(self) -> int:
        """Solo diagnostica: posizione della funzione fra quelle con lo stesso ``fid``."""
        return self.unit.dup_index


def _target_names(target: ast.AST) -> Iterable[ast.Name]:
    """``Name`` legati da un bersaglio di assegnazione (tuple, liste, starred)."""
    if isinstance(target, ast.Name):
        yield target
    elif isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            yield from _target_names(elt)
    elif isinstance(target, ast.Starred):
        yield from _target_names(target.value)


def _variable_bindings(node: ast.AST) -> Iterable[ast.Name]:
    """Binding di variabile ammessi da (a) introdotti direttamente da ``node``."""
    if isinstance(node, ast.Assign):
        for target in node.targets:
            yield from _target_names(target)
    elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
        yield from _target_names(node.target)
    elif isinstance(node, (ast.For, ast.AsyncFor)):
        yield from _target_names(node.target)
    elif isinstance(node, ast.withitem) and node.optional_vars is not None:
        yield from _target_names(node.optional_vars)
    elif isinstance(node, ast.NamedExpr):
        yield from _target_names(node.target)


def _other_bindings(node: ast.AST) -> Iterable[str]:
    """Binding non di variabile (``import``, ``def``, ``class``, ``except as``, ``match``)."""
    if isinstance(node, (*FUNCTION_TYPES, ast.ClassDef)):
        yield node.name
    elif isinstance(node, ast.alias):
        yield node.asname or node.name.split(".")[0]
    elif isinstance(node, ast.ExceptHandler) and node.name:
        yield node.name
    elif type(node).__name__.startswith("Match"):
        for attr in ("name", "rest"):
            value = getattr(node, attr, None)
            if isinstance(value, str):
                yield value


def _module_exclusions(tree: ast.AST) -> set[str]:
    """Nomi esclusi in tutto il modulo: ``global``/``nonlocal``, argomenti con nome, attributi."""
    out: set[str] = set()
    for node in iter_preorder(tree):
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            out.update(node.names)
        elif isinstance(node, ast.keyword) and node.arg:
            out.add(node.arg)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
    return out


def _param_args(fn: ast.AST) -> list[ast.arg]:
    assert isinstance(fn, FUNCTION_TYPES)
    a = fn.args
    out = [*a.posonlyargs, *a.args, *a.kwonlyargs]
    if a.vararg is not None:
        out.append(a.vararg)
    if a.kwarg is not None:
        out.append(a.kwarg)
    return out


_MODULE_DYNAMIC_SCOPE = _DYNAMIC_SCOPE | {"globals"}
_SCOPE_TYPES = (*FUNCTION_TYPES, ast.Lambda, ast.ClassDef)


def _module_scope_nodes(tree: ast.AST) -> list[ast.AST]:
    """Nodi dello scope del modulo in ordine di visita: si salta il contenuto di funzioni,
    ``lambda`` e classi (i corpi di classe sono uno scope a sé: i loro nomi sono attributi)."""
    out: list[ast.AST] = []
    stack = [tree]
    while stack:
        node = stack.pop()
        out.append(node)
        if node is not tree and isinstance(node, _SCOPE_TYPES):
            continue
        stack.extend(reversed(list(ast.iter_child_nodes(node))))
    return out


def _dunder_all(tree: ast.Module) -> set[str]:
    """Nomi elencati in ``__all__`` (assegnazioni e ``+=`` di liste o tuple di stringhe)."""
    out: set[str] = set()
    for node in tree.body:
        targets: list[ast.AST] = []
        value: Optional[ast.AST] = None
        if isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets, value = [node.target], node.value
        if value is None or not any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            continue
        if isinstance(value, (ast.List, ast.Tuple)):
            out.update(
                e.value
                for e in value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            )
    return out


def _uses_dynamic_scope(nodes: Iterable[ast.AST], names: frozenset[str]) -> bool:
    return any(
        isinstance(n, ast.Name) and n.id in names and isinstance(n.ctx, ast.Load) for n in nodes
    )


def _first_bindings(
    nodes: Iterable[ast.AST], index: AstIndex, excluded_binding_ids: frozenset[int]
) -> tuple[dict[str, tuple[int, int, int]], set[str]]:
    """Primo binding di variabile per nome (posizione di visita, riga, colonna) e nomi con
    binding non di variabile."""
    first: dict[str, tuple[int, int, int]] = {}
    other: set[str] = set()
    for node in nodes:
        other.update(_other_bindings(node))
        for name in _variable_bindings(node):
            if id(name) in excluded_binding_ids:
                continue
            pos = index.position[id(name)]
            prev = first.get(name.id)
            if prev is None or pos < prev[0]:
                first[name.id] = (pos, name.lineno, name.col_offset)
    return first, other


def _common_rules(n: str, excluded: set[str], other: set[str]) -> bool:
    """Regole (c), (d), (e), (g) e l'esclusione dei binding non di variabile."""
    return (
        len(n) >= 2  # (c)
        and not n.startswith("_")
        and n not in _EXCLUDED_NAMES  # (g)
        and n not in excluded  # (d), (e)
        and n not in other
    )


def name_sites(
    index: AstIndex,
    include_params: bool = False,
    excluded_binding_ids: frozenset[int] = frozenset(),
    module_level: bool = False,
) -> list[NameSite]:
    """Siti del canale dei nomi (§3.6.1): funzioni in ordine di visita, poi (con
    ``module_level=True``) le variabili di modulo; dentro l'unità, per rango.

    Variabili di modulo (``names.module_level``, [v1.2]): nomi legati nello scope del modulo
    (fuori da funzioni, ``lambda`` e corpi di classe), con le regole (c)–(g) e in più (h) il nome
    non compare in un'istruzione ``global`` del modulo (già in (d)), non è in ``__all__``, non è il
    nome di una funzione, classe o ``import`` del modulo; (i) il modulo non usa ``locals``,
    ``vars``, ``eval``, ``exec``, ``globals`` nel proprio scope. I parametri non riguardano il
    modulo."""
    excluded = _module_exclusions(index.tree)
    nodes_by_unit: dict[int, list[ast.AST]] = {}
    for node in index.order:
        unit = index.unit_of(node)
        if not unit.is_module:
            nodes_by_unit.setdefault(unit.index, []).append(node)
    out: list[NameSite] = []
    for unit in index.functions:
        nodes = nodes_by_unit.get(unit.index, [])
        if _uses_dynamic_scope(nodes, _DYNAMIC_SCOPE):
            continue  # (f)
        assert unit.node is not None
        params = {a.arg for a in _param_args(unit.node)}
        first, other = _first_bindings(nodes, index, excluded_binding_ids)
        if include_params:
            for a in _param_args(unit.node):
                pos = index.position[id(a)]
                if a.arg not in first or pos < first[a.arg][0]:
                    first[a.arg] = (pos, a.lineno, a.col_offset)
        chosen = [
            (pos, n, line, col)
            for n, (pos, line, col) in first.items()
            if _common_rules(n, excluded, other) and (include_params or n not in params)  # (b)
        ]
        for rank, (_, n, line, col) in enumerate(sorted(chosen)):
            out.append(NameSite(unit, n, rank, line, col))
    if module_level:
        out.extend(_module_name_sites(index, excluded, excluded_binding_ids))
    return out


def _module_name_sites(
    index: AstIndex, excluded: set[str], excluded_binding_ids: frozenset[int]
) -> list[NameSite]:
    """Variabili di modulo (vedi ``name_sites``)."""
    tree = index.tree
    assert isinstance(tree, ast.Module)
    scope = _module_scope_nodes(tree)
    if _uses_dynamic_scope(scope, _MODULE_DYNAMIC_SCOPE):
        return []  # (i)
    first, _ = _first_bindings(scope, index, excluded_binding_ids)
    # (h): nomi di funzioni, classi e import in tutto il modulo, e nomi di __all__
    defined = {name for node in index.order for name in _other_bindings(node)}
    blocked = defined | _dunder_all(tree)
    chosen = [
        (pos, n, line, col)
        for n, (pos, line, col) in first.items()
        if _common_rules(n, excluded, set()) and n not in blocked
    ]
    unit = index.unit_of(tree)
    return [
        NameSite(unit, n, rank, line, col) for rank, (_, n, line, col) in enumerate(sorted(chosen))
    ]


# ---------------------------------------------------------------------- P1 / P3


def normalize_name(name: str) -> str:
    """``norm(n)`` di §3.6.2 (``totalCount`` → ``total_count``). Arriva in P1."""
    raise NotImplementedError("P1: normalizzazione dei nomi (§3.6.2)")


def read_style(name: str) -> Optional[int]:
    """Lettura V1 (§4.3): stile a 2 bit o ``None``. Arriva in P1."""
    raise NotImplementedError("P1: lettura V1 (§4.3)")


class Proposer(Protocol):
    """Proponente di nomi alternativi (§3.6.4), deterministico."""

    def propose(self, code: str, function_name: str, var_name: str, k: int = 8) -> list[str]: ...


class StaticProposer:
    """Ripiego non neurale (§3.6.4): sinonimi, suffissi, prefissi. Arriva in P1."""

    def propose(self, code: str, function_name: str, var_name: str, k: int = 8) -> list[str]:
        raise NotImplementedError("P1: StaticProposer (§3.6.4)")
