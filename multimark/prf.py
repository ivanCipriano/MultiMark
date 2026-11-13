"""PRF con chiave (PIPELINE_metodo.md §3.5). Arriva in P1.

```
prf(K, *parts) = HMAC_SHA256(key = K.to_bytes(8, "big"), msg = "|".join(parts).encode("utf-8"))
prf_int(...)   = int.from_bytes(prf(...)[:8], "big")
prf_bit(...)   = prf(...)[-1] & 1
```
"""

from __future__ import annotations


def prf(key: int, *parts: str) -> bytes:
    """HMAC-SHA256 della chiave del benchmark sulle parti unite da ``|``."""
    raise NotImplementedError("P1: prf (§3.5)")


def prf_int(key: int, *parts: str) -> int:
    """Primi 8 byte di ``prf`` come intero big-endian."""
    raise NotImplementedError("P1: prf_int (§3.5)")


def prf_bit(key: int, *parts: str) -> int:
    """Bit meno significativo dell'ultimo byte di ``prf``."""
    raise NotImplementedError("P1: prf_bit (§3.5)")
