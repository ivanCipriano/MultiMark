"""Scheletro di P0: profili di configurazione e moduli di P1 non ancora implementati."""

from __future__ import annotations

from typing import Any, Callable

import pytest

from multimark import codec, detect, embed, linking, names
from multimark.config import Config, mcss_profile, multimark_base


def test_profiles() -> None:
    base = multimark_base()
    assert (base.t, base.message_bits, base.codeword_length) == (2, 24, 32)
    assert (base.linking, base.mask, base.canonical, base.names_variant) == (
        "function_channel", "on", "kind", "V2",
    )  # fmt: skip
    assert base.names_include_params is False and base.voting == "simple"
    mcss = mcss_profile()
    assert (mcss.linking, mcss.mask, mcss.canonical, mcss.names_variant) == (
        "positional", "off", "paper", "V1",
    )  # fmt: skip
    assert mcss.names_include_params is True and mcss.codeword_length == 32
    assert base.names_module_level is False and mcss.names_module_level is True
    assert mcss.read_options.canonical == "paper"


@pytest.mark.parametrize(
    "changes",
    [{"t": 3}, {"linking": "x"}, {"mask": "x"}, {"canonical": "x"}, {"names_variant": "V3"},
     {"names_proposer": "x"}, {"voting": "weighted"}, {"message_bits": 0}],
)  # fmt: skip
def test_config_validation(changes: dict) -> None:
    with pytest.raises(ValueError):
        Config(**changes)


def test_codeword_length() -> None:
    assert [codec.codeword_length(24, t) for t in (0, 2, 4, 8)] == [24, 32, 40, 56]


STUBS: list[tuple[Callable[..., Any], tuple]] = [
    (linking.phi_function, (1, "f", 0, "aug_assign", 0, 32)),
    (linking.phi_positional, (1, 10, 32)),
    (linking.mask, (1, "f", 0, "aug_assign", 0)),
    (names.normalize_name, ("totalCount",)),
    (names.read_style, ("total_count",)),
    (names.StaticProposer().propose, ("", "f", "x")),
    (embed.embed, ("x = 1\n", [0] * 24, 1, multimark_base())),
    (detect.detect, ("x = 1\n", [0] * 24, 1, multimark_base())),
    (detect.binom_tail_score, (10, 5)),
]


@pytest.mark.parametrize("fn,args", STUBS)
def test_p1_stubs_raise(fn: Callable[..., Any], args: tuple) -> None:
    with pytest.raises(NotImplementedError):
        fn(*args)
