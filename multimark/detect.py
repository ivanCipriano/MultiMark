"""Rilevazione (PIPELINE_metodo.md §3.10). Arriva in P1.

Due modalità: confronto con il registro (punteggio principale a ``N_reg = 1``, secondari a 16 e
1024) e decodifica aperta (``bits_correct``, ``decoded_message_open``). Campi di ``extra``
obbligatori in ``EXTRA_FIELDS`` (§3.10.4).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Optional

from multimark.config import Config

DETECT_STATUSES = ("OK", "FAILED")
REGISTRY_SIZES: tuple[int, ...] = (1, 16, 1024)

EXTRA_FIELDS: tuple[str, ...] = (
    "n_sites",
    "n_votes",
    "n_sites_by_channel",
    "n_name_sites",
    "agreement",
    "score_nreg16",
    "score_nreg1024",
    "score_decode",
    "best_nreg16",
    "best_nreg1024",
    "decoded_message_open",
    "decode_status",
    "bits_correct",
    "n_erasures",
    "sites",
    "skipped_sites",
    "library_version",
)


@dataclass
class DetectResult:
    """Esito della rilevazione: stato, punteggio principale, ``extra`` di §3.10.4."""

    status: str
    score: Optional[float] = None
    reason: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


def binom_tail_score(n: int, a: int) -> float:
    """``-log10(P[Bin(N, 1/2) ≥ A])`` esatto con ``math.comb`` (§3.10.2)."""
    raise NotImplementedError("P1: punteggio (§3.10.2)")


def detect(
    code: str,
    expected: Sequence[int],
    key: int,
    cfg: Config,
    registry_sizes: Sequence[int] = REGISTRY_SIZES,
) -> DetectResult:
    """Rileva il watermark in ``code`` rispetto al messaggio atteso ``expected``."""
    raise NotImplementedError("P1: rilevazione (§3.10)")
