"""Regola di scope per i nomi nuovi (§3.6.4 [v1.2.1], MD16) e ordine del pool posizionale di
``mcss`` (paper p. 5, passo 4: prima tutte le variabili, poi i siti strutturali)."""

from __future__ import annotations

from multimark._astindex import AstIndex
from multimark.config import mcss_profile
from multimark.embed import _ScopeNames
from multimark.layout import build_layout

CODE = """\
LIMIT_VALUE = 3


def f(total_count):
    item_list = [1]
    if total_count is None:
        return LIMIT_VALUE
    return item_list


def g(total_count):
    item_list = []
    x = total_count + 1
    return item_list, x
"""


def test_pool_order_names_first_then_structural() -> None:
    cfg = mcss_profile()
    layout = build_layout(AstIndex.from_code(CODE), cfg, 7)
    kinds = [s.is_name for s in layout.slots]
    assert any(kinds) and not all(kinds)
    first_structural = kinds.index(False)
    assert all(kinds[:first_structural]) and not any(kinds[first_structural:])
    # le variabili occupano 2 posizioni consecutive del flusso phi, poi i siti strutturali
    n_names = first_structural
    assert all(len(s.indices) == 2 for s in layout.slots[:n_names])
    assert all(len(s.indices) == 1 for s in layout.slots[n_names:])


def test_scope_names_allow_same_new_name_in_two_functions() -> None:
    cfg = mcss_profile()
    index = AstIndex.from_code(CODE)
    layout = build_layout(index, cfg, 7)
    scope = _ScopeNames(index)
    by_unit = {}
    for slot in layout.names:
        assert slot.name is not None
        if slot.name.name == "item_list":
            by_unit[slot.name.unit.name] = slot
    sf, sg = by_unit["f"], by_unit["g"]
    scope.add(sf, "itemList")
    assert "itemList" in scope.for_slot(sf)
    assert "itemList" not in scope.for_slot(sg)  # due funzioni diverse: stesso nome ammesso
    assert "LIMIT_VALUE" in scope.for_slot(sf)  # nome di modulo letto da f
    assert "LIMIT_VALUE" not in scope.for_slot(sg)  # g non lo legge


def test_scope_names_module_variable_renames_propagate() -> None:
    cfg = mcss_profile()
    index = AstIndex.from_code(CODE)
    layout = build_layout(index, cfg, 7)
    scope = _ScopeNames(index)
    module = next(s for s in layout.names if s.name is not None and s.name.unit.is_module)
    local_f = next(s for s in layout.names if s.name is not None and s.name.unit.name == "f")
    local_g = next(s for s in layout.names if s.name is not None and s.name.unit.name == "g")
    scope.add(module, "limitValue")
    assert "limitValue" in scope.for_slot(local_f)  # f legge la variabile di modulo
    assert "limitValue" not in scope.for_slot(local_g)
    scope.add(local_g, "fooBar")
    assert "fooBar" in scope.for_slot(module)  # per il modulo: tutti i nomi già scelti
