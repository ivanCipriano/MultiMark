"""Profili di configurazione (§3.11)."""

from __future__ import annotations

import pytest

from multimark import codec
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
    assert (base.channels, mcss.channels) == ("extended", "mcss8")
    assert (base.code_matrix, mcss.code_matrix) == ("dmin4", "random")
    assert mcss.read_options.canonical == "paper"


@pytest.mark.parametrize(
    "changes",
    [{"t": 3}, {"linking": "x"}, {"mask": "x"}, {"canonical": "x"}, {"names_variant": "V3"},
     {"code_matrix": "x"},
     {"names_proposer": "x"}, {"voting": "weighted"}, {"message_bits": 0},
     {"channels": "all"}],
)  # fmt: skip
def test_config_validation(changes: dict) -> None:
    with pytest.raises(ValueError):
        Config(**changes)


def test_codeword_length() -> None:
    assert [codec.codeword_length(24, t) for t in (0, 2, 4, 8)] == [24, 32, 40, 56]
