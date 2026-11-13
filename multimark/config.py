"""Opzioni di configurazione (PIPELINE_metodo.md §3.11), con i due profili ``multimark`` e ``mcss``.

I nomi coincidono 1:1 con quelli del protocollo. ``message_bits`` lo fissa l'adapter (24).
``registry_seed`` è il ``global_seed`` del benchmark e non entra nel ``config_hash``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from multimark.channels import CANONICAL_MODES, CHANNEL_SET_NAMES, ReadOptions
from multimark.linking import LINKING_MODES
from multimark.names import NAME_VARIANTS

T_VALUES = (0, 2, 4, 8)
MASK_MODES = ("on", "off")
PROPOSERS = ("static", "neural")
VOTING_MODES = ("simple", "weighted", "weighted_erasure")


@dataclass(frozen=True)
class Config:
    """Configurazione completa di inserimento e rilevazione."""

    t: int = 2
    message_bits: int = 24
    linking: str = "function_channel"
    mask: str = "on"
    canonical: str = "kind"
    names_variant: str = "V2"
    names_proposer: str = "static"  # ``neural`` da P3 (§3.11)
    names_include_params: bool = False
    # [v1.2] variabili di modulo nel canale dei nomi: decisione O di §7, ``false`` fino ad allora
    names_module_level: bool = False
    # [v1.2] canali strutturali: ``extended`` (1–14, base) o ``mcss8`` (1–8)
    channels: str = "extended"
    voting: str = "simple"
    channel_weights: Optional[str] = None
    registry_seed: Optional[int] = None

    def __post_init__(self) -> None:
        checks = (
            ("t", self.t, T_VALUES),
            ("linking", self.linking, LINKING_MODES),
            ("mask", self.mask, MASK_MODES),
            ("canonical", self.canonical, CANONICAL_MODES),
            ("names.variant", self.names_variant, NAME_VARIANTS),
            ("names.proposer", self.names_proposer, PROPOSERS),
            ("voting", self.voting, VOTING_MODES),
            ("channels", self.channels, CHANNEL_SET_NAMES),
        )
        for name, value, allowed in checks:
            if value not in allowed:
                raise ValueError(f"{name} must be one of {allowed}: {value!r}")
        if self.message_bits <= 0:
            raise ValueError("message_bits must be positive")
        if self.voting != "simple" and self.channel_weights is None:
            raise ValueError("channel_weights is required with weighted voting")

    @property
    def codeword_length(self) -> int:
        """``B = message_bits + 4t``."""
        return self.message_bits + 4 * self.t

    @property
    def read_options(self) -> ReadOptions:
        return ReadOptions(canonical=self.canonical, channels=self.channels)

    def with_(self, **changes: object) -> Config:
        return replace(self, **changes)  # type: ignore[arg-type]


def multimark_base() -> Config:
    """Configurazione di base di ``multimark`` (§0.1, §3.11; proponente statico fino a P2)."""
    return Config()


def mcss_profile() -> Config:
    """Profilo ``mcss`` (§3.11, §4)."""
    return Config(
        linking="positional",
        mask="off",
        canonical="paper",
        names_variant="V1",
        names_include_params=True,
        names_module_level=True,
        channels="mcss8",
    )
