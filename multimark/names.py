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
import builtins
import json
import keyword
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional, Protocol

from multimark._astindex import FUNCTION_TYPES, AstIndex, FunctionUnit, iter_preorder
from multimark.prf import prf_bit, prf_int

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
    #: posizione di visita del primo binding (``AstIndex.order``); -1 se ignota
    position: int = -1

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


def _class_body_ids(tree: ast.AST) -> set[int]:
    """Id dei nodi il cui scope più interno è il corpo di una classe (non i metodi): i loro nomi
    sono attributi della classe, non variabili (come per T1.4, che usa gli scope di LibCST)."""
    out: set[int] = set()
    stack: list[tuple[ast.AST, bool]] = [(tree, False)]
    while stack:
        node, in_class = stack.pop()
        if in_class:
            out.add(id(node))
        if isinstance(node, ast.ClassDef):
            child_flag = True
        elif isinstance(node, (*FUNCTION_TYPES, ast.Lambda)):
            child_flag = False
        else:
            child_flag = in_class
        for child in ast.iter_child_nodes(node):
            stack.append((child, child_flag))
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
    in_class_body = _class_body_ids(index.tree)
    nodes_by_unit: dict[int, list[ast.AST]] = {}
    for node in index.order:
        unit = index.unit_of(node)
        if not unit.is_module and id(node) not in in_class_body:
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
        for rank, (pos, n, line, col) in enumerate(sorted(chosen)):
            out.append(NameSite(unit, n, rank, line, col, pos))
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
        NameSite(unit, n, rank, line, col, pos)
        for rank, (pos, n, line, col) in enumerate(sorted(chosen))
    ]


# ---------------------------------------------------------------------- norm e stili (§3.6.2, §4.3)

_SEGMENT = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+[0-9]*|[0-9]+")

#: Stili V1 (§4.3): indice = valore a 2 bit.
STYLES = ("snake", "camel", "pascal", "caps")


def segments(name: str) -> list[str]:
    """Segmenti di un nome: si spezza su ``_``, sui cambi minuscolo→maiuscolo e sulle sequenze
    di maiuscole seguite da minuscola. Le cifre stanno con le minuscole che le precedono
    (``item2Count`` → ``item2``, ``Count``). TODO(ivan): la pipeline non dice nulla sulle cifre."""
    out: list[str] = []
    for part in name.split("_"):
        out.extend(_SEGMENT.findall(part))
    return out


def normalize_name(name: str) -> str:
    """``norm(n)`` di §3.6.2: segmenti in minuscolo uniti da ``_``."""
    return "_".join(s.lower() for s in segments(name))


def _cap(seg: str) -> str:
    return seg[:1].upper() + seg[1:].lower()


def render_style(segs: Sequence[str], style: int) -> str:
    """Nome nello stile ``style`` (0 snake, 1 camel, 2 Pascal, 3 ALL_CAPS) dai segmenti."""
    low = [s.lower() for s in segs]
    if style == 0:
        return "_".join(low)
    if style == 1:
        return low[0] + "".join(_cap(s) for s in low[1:])
    if style == 2:
        return "".join(_cap(s) for s in low)
    if style == 3:
        return "_".join(s.upper() for s in low)
    raise ValueError(f"style must be 0..3: {style}")


def read_style(name: str) -> Optional[int]:
    """Lettura V1 (§4.3): stile a 2 bit, solo per nomi con almeno 2 segmenti; altrimenti
    ``None``. Un nome che non coincide con nessuna resa dei suoi segmenti dà ``None``."""
    segs = segments(name)
    if len(segs) < 2:
        return None
    for style in range(4):
        if render_style(segs, style) == name:
            return style
    return None


def read_style_v1b(name: str) -> Optional[int]:
    """Lettura V1b: snake 0, camel 1, altri stili ``None``."""
    style = read_style(name)
    return style if style in (0, 1) else None


def name_bit(key: int, name: str) -> int:
    """Lettura V2 (e V2b): ``prf_bit(K, "name", norm(n))``."""
    return prf_bit(key, "name", normalize_name(name))


def name_slot(key: int, name: str, b: int) -> int:
    """Indirizzo V2b: ``prf_int(K, "name-slot", norm(n)) mod B``."""
    return prf_int(key, "name-slot", normalize_name(name)) % b


# ---------------------------------------------------------------------- suffissi V1 (§4.2 punto 4)


def type_suffix(value: Optional[ast.AST]) -> str:
    """Suffisso per estendere un nome di una parola (V1, §4.2 punto 4), dal valore del primo
    binding se letterale o costruttore: ``int`` → ``count``, ``float`` → ``val``, ``str`` →
    ``str``, ``list`` → ``list``, ``dict`` → ``map``, ``bool`` → ``flag``, altrimenti ``val``."""
    if isinstance(value, ast.Constant):
        v = value.value
        if isinstance(v, bool):
            return "flag"
        if isinstance(v, int):
            return "count"
        if isinstance(v, float):
            return "val"
        if isinstance(v, str):
            return "str"
        return "val"
    if isinstance(value, (ast.List, ast.ListComp)):
        return "list"
    if isinstance(value, (ast.Dict, ast.DictComp)):
        return "map"
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
        return {"int": "count", "float": "val", "str": "str", "list": "list", "dict": "map",
                "bool": "flag"}.get(value.func.id, "val")  # fmt: skip
    return "val"


def first_binding_value(index: AstIndex, site: NameSite) -> Optional[ast.AST]:
    """Valore assegnato dal primo binding della variabile (``None`` se non è un'assegnazione)."""
    if site.position < 0:
        return None
    node = index.order[site.position]
    parent = index.parent_of(node)
    if isinstance(parent, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
        return parent.value
    return None


# ---------------------------------------------------------------------- validità e proponenti

_SNAKE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")
# Parole chiave «soft» fissate a mano: ``keyword.softkwlist`` non esiste in Python 3.9 e la validità
# di un nome non deve dipendere dalla versione dell'interprete.
_RESERVED = frozenset(keyword.kwlist) | frozenset({"match", "case", "type", "_"})
_BUILTINS = frozenset(builtins.__dict__)


def identifiers_in(tree: ast.AST) -> set[str]:
    """Tutti gli identificatori del modulo: nomi, parametri, attributi, ``def``/``class``,
    ``import``, argomenti con nome, ``global``/``nonlocal``."""
    out: set[str] = set()
    for node in iter_preorder(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.arg):
            out.add(node.arg)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, (*FUNCTION_TYPES, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.alias):
            out.add(node.asname or node.name.split(".")[0])
            out.update(node.name.split("."))
        elif isinstance(node, ast.keyword) and node.arg:
            out.add(node.arg)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            out.update(node.names)
    return out


def valid_new_name(candidate: str, original: str, used: set[str], snake: bool = True) -> bool:
    """Validità di un nome nuovo (§3.6.4): identificatore, ``snake_case`` (solo V2/V2b),
    ``len ≥ 2``, non riservato, non builtin, non già usato nel modulo, diverso dall'originale, non
    termina con ``_`` e non inizia con ``_``; mai ``self``/``cls`` (resta un sito dei nomi)."""
    return (
        candidate.isidentifier()
        and (not snake or _SNAKE.fullmatch(candidate) is not None)
        and len(candidate) >= 2
        and candidate not in _RESERVED
        and candidate not in _BUILTINS
        and candidate not in used
        and candidate != original
        and not candidate.endswith("_")
        and not candidate.startswith("_")
        and candidate not in _EXCLUDED_NAMES
    )


class Proposer(Protocol):
    """Proponente di nomi alternativi (§3.6.4), deterministico."""

    def propose(self, code: str, function_name: str, var_name: str, k: int = 8) -> list[str]: ...


SUFFIXES = ("value", "val", "item", "list", "count", "idx", "tmp", "res")
PREFIXES = ("cur_", "new_", "the_")


@lru_cache(maxsize=1)
def synonyms() -> dict[str, tuple[str, ...]]:
    """Dizionario fisso ``multimark/data/name_synonyms.json`` (nome normalizzato → sinonimi)."""
    path = Path(__file__).with_name("data") / "name_synonyms.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: tuple(v) for k, v in data.items() if not k.startswith("_")}


class StaticProposer:
    """Ripiego non neurale (§3.6.4). Candidati, in quest'ordine: (1) sinonimi di ``norm(n)`` dal
    dizionario fisso; (2) ``norm(n) + "_" + suffisso``; (3) prefisso + ``norm(n)``. Restituisce i
    primi ``k`` candidati validi (§3.6.4) rispetto al codice dato."""

    def propose(self, code: str, function_name: str, var_name: str, k: int = 8) -> list[str]:
        base = normalize_name(var_name)
        raw = [*synonyms().get(base, ()), *(f"{base}_{s}" for s in SUFFIXES),
               *(f"{p}{base}" for p in PREFIXES)]  # fmt: skip
        used = identifiers_in(ast.parse(code))
        out: list[str] = []
        for cand in raw:
            if cand not in out and valid_new_name(cand, var_name, used):
                out.append(cand)
            if len(out) == k:
                break
        return out
