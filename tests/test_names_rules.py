"""Canale dei nomi: normalizzazione (§3.6.2), stili V1/V1b (§4.3), V2/V2b, suffissi (§4.2 punto
4), validità dei candidati e ``StaticProposer`` (§3.6.4)."""

from __future__ import annotations

import ast
import builtins
import keyword
import re

import pytest

from multimark._astindex import AstIndex
from multimark.names import (
    PREFIXES,
    SUFFIXES,
    StaticProposer,
    first_binding_value,
    name_bit,
    name_sites,
    name_slot,
    normalize_name,
    read_style,
    read_style_v1b,
    render_style,
    segments,
    synonyms,
    type_suffix,
    valid_new_name,
)
from multimark.prf import prf_bit, prf_int


@pytest.mark.parametrize(
    "name,norm",
    [("totalCount", "total_count"), ("TotalCount", "total_count"), ("TOTAL_COUNT", "total_count"),
     ("total_count", "total_count"), ("HTTPResponse", "http_response"), ("x", "x"),
     ("item2Count", "item2_count"), ("getHTTP", "get_http"), ("a__b", "a_b")],
)  # fmt: skip
def test_normalize_name(name: str, norm: str) -> None:
    assert normalize_name(name) == norm


@pytest.mark.parametrize(
    "name,style",
    [("total_count", 0), ("totalCount", 1), ("TotalCount", 2), ("TOTAL_COUNT", 3),
     ("total", None), ("HTTPResponse", None), ("total_Count", None), ("a_b_c", 0)],
)  # fmt: skip
def test_read_style(name: str, style: object) -> None:
    assert read_style(name) == style


def test_render_and_read_roundtrip() -> None:
    for name in ("max_value", "itemCount", "row_index2", "best_sum_so_far"):
        segs = segments(name)
        for style in range(4):
            rendered = render_style(segs, style)
            assert read_style(rendered) == style
            assert normalize_name(rendered) == normalize_name(name)
    with pytest.raises(ValueError):
        render_style(["a", "b"], 4)


def test_v1b() -> None:
    assert [read_style_v1b(n) for n in ("a_b", "aB", "AB", "A_B", "ab")] == [0, 1, None, None, None]


def test_v2_and_v2b_depend_only_on_normalized_name() -> None:
    assert (
        name_bit(5, "totalCount") == name_bit(5, "total_count") == prf_bit(5, "name", "total_count")
    )
    assert name_slot(5, "TOTAL_COUNT", 32) == prf_int(5, "name-slot", "total_count") % 32


@pytest.mark.parametrize(
    "value,suffix",
    [("0", "count"), ("1.5", "val"), ("'a'", "str"), ("True", "flag"), ("[]", "list"),
     ("[x for x in y]", "list"), ("{}", "map"), ("dict()", "map"), ("int(s)", "count"),
     ("f(x)", "val"), ("None", "val")],
)  # fmt: skip
def test_type_suffix(value: str, suffix: str) -> None:
    node = ast.parse(f"v = {value}").body[0]
    assert isinstance(node, ast.Assign)
    assert type_suffix(node.value) == suffix
    assert type_suffix(None) == "val"


def test_first_binding_value_and_position() -> None:
    index = AstIndex.from_code("def f(a):\n    total = 0\n    for item in a:\n        pass\n")
    sites = name_sites(index)
    assert [s.name for s in sites] == ["total", "item"]
    assert all(s.position >= 0 for s in sites)
    value = first_binding_value(index, sites[0])
    assert isinstance(value, ast.Constant) and value.value == 0
    assert first_binding_value(index, sites[1]) is None


def test_class_bodies_inside_functions_are_not_bindings() -> None:
    code = (
        "def f():\n    class Local:\n        attr_name = 1\n        def method(self):\n"
        "            inner = 2\n            return inner\n    outer = Local\n    return outer\n"
    )
    assert [s.name for s in name_sites(AstIndex.from_code(code))] == ["inner", "outer"]


def test_valid_new_name() -> None:
    used = {"taken", "total"}
    assert valid_new_name("new_total", "total", used)
    for bad in ("taken", "total", "list", "class", "match", "x", "_hidden", "trailing_", "Upper",
                "two-words", "self", "cls"):  # fmt: skip
        assert not valid_new_name(bad, "total", used), bad
    assert valid_new_name("totalCount", "total", used, snake=False)


def test_synonyms_dictionary() -> None:
    data = synonyms()
    snake = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")
    assert len(data) >= 300
    for key, values in data.items():
        assert snake.fullmatch(key), key
        assert values, key
        for v in values:
            assert snake.fullmatch(v) and v not in builtins.__dict__ and not keyword.iskeyword(v)
            assert v != key


def test_static_proposer_order_and_validity() -> None:
    code = "def f(a):\n    count = 0\n    counter = 1\n    return count + counter\n"
    got = StaticProposer().propose(code, "f", "count", k=8)
    assert len(got) == 8
    assert got[0] == "total"  # primo sinonimo valido ("counter" è già usato nel modulo)
    assert "counter" not in got and "count" not in got
    assert got == StaticProposer().propose(code, "f", "count", k=8)  # deterministico


def test_static_proposer_without_synonyms_uses_suffixes_then_prefixes() -> None:
    code = "def f():\n    zorblax = 1\n    return zorblax\n"
    got = StaticProposer().propose(code, "f", "zorblax", k=20)
    expected = [f"zorblax_{s}" for s in SUFFIXES] + [f"{p}zorblax" for p in PREFIXES]
    assert got == expected


def test_static_proposer_normalizes_camel_case() -> None:
    got = StaticProposer().propose("def f():\n    maxVal = 1\n", "f", "maxVal", k=3)
    assert got[:3] == ["maximum", "largest", "highest"]
