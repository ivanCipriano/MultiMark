"""Risoluzione degli scope sull'``ast`` per ``canonical.same_kind = binding_order``
(PIPELINE_metodo.md §3.11 [v1.3.2], MD28 di ``docs/mcss_deviations.md``).

Per ogni ``Name`` letto dice a quale variabile si riferisce, con le regole di Python, e dove sta il
primo binding di quella variabile nel suo scope:

- scope: modulo, funzione, ``lambda``, corpo di classe, comprehension (``ListComp``, ``SetComp``,
  ``DictComp``, ``GeneratorExp``);
- dentro una funzione o una ``lambda``: decoratori, valori di default e annotazioni sono dello
  scope esterno, i parametri dello scope interno; il primo iterabile di una comprehension è dello
  scope esterno, il resto (bersagli, condizioni, altri iterabili, elemento) della comprehension;
  il bersaglio di un ``NamedExpr`` è dello scope non comprehension più vicino (PEP 572);
- un nome legato in uno scope è locale in tutto lo scope; la ricerca sale negli scope esterni
  saltando i corpi di classe (che si vedono solo dall'interno);
- binding: ``Name`` in ``Store`` (assegnazioni, ``for``, ``with``, bersagli di comprehension),
  parametri, ``NamedExpr``; ``del`` rende il nome locale ma non è un primo binding; ``import``,
  ``def``, ``class``, ``except ... as`` e i pattern di ``match`` sono binding non di variabile.

Si usa solo l'``ast`` della libreria standard (§0.1); le posizioni sono quelle dell'ordine di
visita di ``AstIndex``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Optional

from multimark._astindex import FUNCTION_TYPES, AstIndex

_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)

#: Modi di un binding: ``param`` (parametro), ``store`` (``Name`` in ``Store``), ``walrus``
#: (bersaglio di ``NamedExpr``), ``del``, ``other`` (binding non di variabile).
BINDING_HOWS = ("param", "store", "walrus", "del", "other")


@dataclass(frozen=True)
class Binding:
    """Variabile a cui si riferisce un ``Name``: scope, nome e primo binding.

    ``first`` è la posizione di visita del primo binding (``del`` escluso) e ``first_how`` il suo
    modo; ``variable`` è falso se il nome ha nello scope un binding non di variabile."""

    scope_kind: str
    scope_position: int
    name: str
    first: int
    first_how: str
    variable: bool

    @property
    def identity(self) -> tuple[int, str]:
        """Identità della variabile (stesso scope e stesso nome = stessa variabile)."""
        return (self.scope_position, self.name)


@dataclass
class _Scope:
    node: ast.AST
    parent: Optional[_Scope]
    kind: str  # module | function | lambda | class | comprehension
    position: int
    bindings: dict[str, list[tuple[int, str]]] = field(default_factory=dict)

    def bind(self, name: str, position: int, how: str) -> None:
        self.bindings.setdefault(name, []).append((position, how))


class ScopeResolver:
    """Scope di tutti i ``Name`` letti del modulo e binding delle variabili."""

    def __init__(self, index: AstIndex) -> None:
        self.index = index
        self._loads: dict[int, _Scope] = {}
        #: nomi dichiarati ``global`` o ``nonlocal`` in qualche punto del modulo
        self.declared: set[str] = set()
        self.module = _Scope(index.tree, None, "module", 0)
        stack: list[tuple[ast.AST, _Scope]] = [(index.tree, self.module)]
        while stack:
            node, scope = stack.pop()
            stack.extend(self._enter(node, scope))

    def _pos(self, node: ast.AST) -> int:
        return self.index.position[id(node)]

    def _new(self, node: ast.AST, parent: _Scope, kind: str) -> _Scope:
        return _Scope(node, parent, kind, self._pos(node))

    def _arguments(self, args: ast.arguments, outer: _Scope, inner: _Scope) -> list:
        out: list[tuple[ast.AST, _Scope]] = []
        params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
        params += [a for a in (args.vararg, args.kwarg) if a is not None]
        for a in params:
            inner.bind(a.arg, self._pos(a), "param")
            if a.annotation is not None:
                out.append((a.annotation, outer))
        out += [(d, outer) for d in (*args.defaults, *args.kw_defaults) if d is not None]
        return out

    def _enter(self, node: ast.AST, scope: _Scope) -> list[tuple[ast.AST, _Scope]]:
        """Registra i binding introdotti da ``node`` e restituisce i figli con il loro scope
        (l'ordine non conta: le posizioni vengono da ``AstIndex``)."""
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                self._loads[id(node)] = scope
            else:
                how = "store" if isinstance(node.ctx, ast.Store) else "del"
                scope.bind(node.id, self._pos(node), how)
            return []
        if isinstance(node, FUNCTION_TYPES):
            scope.bind(node.name, self._pos(node), "other")
            inner = self._new(node, scope, "function")
            out: list[tuple[ast.AST, _Scope]] = [(d, scope) for d in node.decorator_list]
            out += self._arguments(node.args, scope, inner)
            if node.returns is not None:
                out.append((node.returns, scope))
            return out + [(s, inner) for s in node.body]
        if isinstance(node, ast.Lambda):
            inner = self._new(node, scope, "lambda")
            return [*self._arguments(node.args, scope, inner), (node.body, inner)]
        if isinstance(node, ast.ClassDef):
            scope.bind(node.name, self._pos(node), "other")
            inner = self._new(node, scope, "class")
            outer = [*node.decorator_list, *node.bases, *node.keywords]
            return [(c, scope) for c in outer] + [(s, inner) for s in node.body]
        if isinstance(node, _COMPREHENSIONS):
            inner = self._new(node, scope, "comprehension")
            gens = node.generators
            out = [(gens[0].iter, scope)]
            for i, gen in enumerate(gens):
                out.append((gen.target, inner))
                if i:
                    out.append((gen.iter, inner))
                out += [(c, inner) for c in gen.ifs]
            elts = (node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,)
            return out + [(e, inner) for e in elts]
        if isinstance(node, ast.NamedExpr):
            target_scope = scope
            while target_scope.kind == "comprehension" and target_scope.parent is not None:
                target_scope = target_scope.parent
            if isinstance(node.target, ast.Name):
                target_scope.bind(node.target.id, self._pos(node.target), "walrus")
            return [(node.value, scope)]
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            self.declared.update(node.names)
            return []
        if isinstance(node, ast.alias):
            scope.bind(node.asname or node.name.split(".")[0], self._pos(node), "other")
            return []
        if isinstance(node, ast.ExceptHandler) and node.name:
            scope.bind(node.name, self._pos(node), "other")
        elif type(node).__name__.startswith("Match"):
            for attr in ("name", "rest"):
                value = getattr(node, attr, None)
                if isinstance(value, str):
                    scope.bind(value, self._pos(node), "other")
        return [(c, scope) for c in ast.iter_child_nodes(node)]

    def binding(self, name: ast.Name) -> Optional[Binding]:
        """Variabile del ``Name`` letto ``name``; ``None`` se non ha binding in nessuno scope
        visibile (builtin o nome non definito), se il nome è dichiarato ``global``/``nonlocal`` nel
        modulo, se ha solo binding ``del`` o se ``name`` non è un ``Name`` letto."""
        scope = self._loads.get(id(name))
        if scope is None or name.id in self.declared:
            return None
        current: Optional[_Scope] = scope
        while current is not None:
            if current.kind == "class" and current is not scope:
                current = current.parent  # i corpi di classe non si vedono dagli scope interni
                continue
            entries = current.bindings.get(name.id)
            if entries:
                return _binding_of(current, name.id, entries)
            current = current.parent
        return None


def _binding_of(scope: _Scope, name: str, entries: list[tuple[int, str]]) -> Optional[Binding]:
    real = sorted(e for e in entries if e[1] != "del")
    if not real:
        return None
    first, how = real[0]
    variable = all(h != "other" for _, h in entries)
    return Binding(scope.kind, scope.position, name, first, how, variable)
