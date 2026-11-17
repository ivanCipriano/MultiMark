"""Regola di scope per i nomi nuovi (§3.6.4 [v1.2.1], MD16) e ordine del pool posizionale di
``mcss`` (paper p. 5, passo 4: prima tutte le variabili, poi i siti strutturali)."""

from __future__ import annotations

from multimark._astindex import AstIndex
from multimark.config import mcss_profile
from multimark.embed import _ScopeNames
from multimark.layout import build_layout
from multimark.names import render_style

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
    # MD20: per il modulo contano i nomi scelti nelle unità che leggono la variabile (f la legge,
    # g no)
    assert "fooBar" not in scope.for_slot(module)
    scope.add(local_f, "barBaz")
    assert "barBaz" in scope.for_slot(module)


def test_scope_names_parameter_with_module_name_is_not_a_reader() -> None:
    # Caso della fixture p00004: il parametro ``a`` di una funzione diventa ``aVal``; la variabile
    # di modulo ``a`` può diventare ``aVal`` anch'essa, perché la funzione non la legge.
    code = "def inverse(a, b):\n    return a - b\n\n\na, b = 1, 2\nprint(inverse(a, b))\n"
    cfg = mcss_profile().with_(names_single_letter="extend_except_loop")
    index = AstIndex.from_code(code)
    layout = build_layout(index, cfg, 7)
    scope = _ScopeNames(index)
    param = next(s for s in layout.names if s.name is not None and s.name.unit.name == "inverse")
    module = next(s for s in layout.names if s.name is not None and s.name.unit.is_module)
    assert param.name is not None and module.name is not None
    scope.add(param, render_style([param.name.name, "val"], 1))
    assert "aVal" not in scope.for_slot(module)
