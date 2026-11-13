"""Inserimento (PIPELINE_metodo.md §3.9). Arriva in P1.

Stati (§3.9): ``OK`` se ``N ≥ B``; ``PARTIAL`` se ``0 < N < B``; ``FAILED`` se ``N = 0``, errore di
sintassi, ``rewrite_mismatch`` o eccezione.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Optional

from multimark.config import Config

EMBED_STATUSES = ("OK", "PARTIAL", "FAILED")


@dataclass
class EmbedResult:
    """Esito dell'inserimento: codice marcato, stato, motivo del fallimento, campi di ``extra``."""

    code: str
    status: str
    reason: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)


def embed(code: str, message: Sequence[int], key: int, cfg: Config) -> EmbedResult:
    """Marca ``code`` con il messaggio ``message`` (bit) e la chiave ``key``."""
    raise NotImplementedError("P1: inserimento (§3.9)")
