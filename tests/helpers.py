"""Utilità comuni ai test di lettura."""

from __future__ import annotations

import textwrap

from multimark.channels import ReadOptions
from multimark.sites import Site, find_sites_in_code


def src(code: str) -> str:
    return textwrap.dedent(code).lstrip("\n")


def read(code: str, canonical: str = "kind", guards: bool = True) -> list[Site]:
    return find_sites_in_code(src(code), ReadOptions(canonical=canonical, guards=guards))


def channel_values(code: str, channel: str, **opts: object) -> list[int]:
    """Valori letti dei siti di un canale, in ordine di rango."""
    return [s.value for s in read(code, **opts) if s.channel == channel]  # type: ignore[arg-type]


def keys_values(code: str, **opts: object) -> list[tuple[tuple[str, int, str, int], int]]:
    return [(s.key, s.value) for s in read(code, **opts)]  # type: ignore[arg-type]
