"""Rinomina coerente di tutte le variabili, per i test di proprietà dell'indipendenza dai nomi
(``canonical.same_kind = binding_order``, MD28).

Una variabile è un gruppo di binding con lo stesso nome nello stesso scope di LibCST (modulo,
funzione, ``lambda``, comprehension), con tutti i suoi accessi. Due modi:

- ``split_scopes=False`` (per nome): ogni nome di variabile diventa ``zq<k>`` in tutte le variabili
  che lo portano, quindi due variabili omonime restano omonime; un nome si rinomina solo se tutte
  le sue variabili si possono rinominare;
- ``split_scopes=True`` (per variabile): ogni variabile riceve un nome suo, anche se ha lo stesso
  nome di una variabile di un altro scope.

``k`` segue un ordine casuale dato da ``seed``. Restano fuori: attributi di classe (scope di
classe; con ``split_scopes=False`` anche le variabili omonime), nomi di funzioni, classi e
``import`` (e, per nome, le variabili omonime), nomi ``global``/``nonlocal``, nomi che coprono un
builtin, nomi che iniziano con ``__``.
"""

from __future__ import annotations

import ast
import builtins
import random
from typing import Any, Optional

import libcst as cst
from libcst.metadata import ClassScope, MetadataWrapper, ScopeProvider

from multimark.names import identifiers_in

_BUILTINS = frozenset(builtins.__dict__)


class _Rename(cst.CSTTransformer):
    def __init__(self, names: dict[int, str]) -> None:
        super().__init__()
        self.names = names

    def leave_Name(self, original_node: cst.Name, updated_node: cst.Name) -> Any:
        new = self.names.get(id(original_node))
        return updated_node.with_changes(value=new) if new is not None else updated_node


def _declared(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            out.update(node.names)
    return out


def _group(scope: Any, name: str) -> Optional[list[cst.Name]]:
    """Nodi ``Name`` di una variabile (binding e accessi); ``None`` se non è rinominabile."""
    nodes: list[cst.Name] = []
    for assignment in scope.assignments[name]:
        node = getattr(assignment, "node", None)
        if isinstance(node, cst.Param):
            node = node.name
        if not isinstance(node, cst.Name):
            return None
        nodes.append(node)
        for access in assignment.references:
            if not isinstance(access.node, cst.Name):
                return None
            nodes.append(access.node)
    return nodes


def rename_all_variables(code: str, seed: int, split_scopes: bool = True) -> tuple[str, int]:
    """Codice con le variabili rinominate e numero di nomi nuovi usati."""
    tree = ast.parse(code)
    skip = _declared(tree) | _BUILTINS
    existing = identifiers_in(tree)
    wrapper = MetadataWrapper(cst.parse_module(code))
    scopes = {id(s): s for s in wrapper.resolve(ScopeProvider).values() if s is not None}
    groups: dict[tuple, list[cst.Name]] = {}
    blocked: set[str] = set()
    for sid, scope in scopes.items():
        names = sorted({a.name for a in scope.assignments})
        for name in names:
            if name in skip or name.startswith("__"):
                continue
            nodes = None if isinstance(scope, ClassScope) else _group(scope, name)
            if nodes is None:
                blocked.add(name)
            elif nodes:
                groups[(name, sid)] = nodes
    if split_scopes:
        units = [[g] for g in groups.values()]
    else:
        by_name: dict[str, list[list[cst.Name]]] = {}
        for (name, _), nodes in groups.items():
            if name not in blocked:
                by_name.setdefault(name, []).append(nodes)
        units = [by_name[n] for n in sorted(by_name)]
    order = list(range(len(units)))
    random.Random(seed).shuffle(order)
    targets: dict[int, str] = {}
    for k, unit in zip(order, units):
        new = f"zq{k}"
        assert new not in existing
        for nodes in unit:
            for node in nodes:
                targets[id(node)] = new
    return wrapper.module.visit(_Rename(targets)).code, len(units)
