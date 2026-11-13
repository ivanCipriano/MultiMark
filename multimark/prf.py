"""PRF con chiave (PIPELINE_metodo.md §3.5) e seme derivato del benchmark (§3.10.1).

```
prf(K, *parts) = HMAC_SHA256(key = K.to_bytes(8, "big"), msg = "|".join(parts).encode("utf-8"))
prf_int(...)   = int.from_bytes(prf(...)[:8], "big")
prf_bit(...)   = prf(...)[-1] & 1
```
"""

from __future__ import annotations

import hashlib
import hmac


def prf(key: int, *parts: str) -> bytes:
    """HMAC-SHA256 della chiave del benchmark (8 byte big-endian) sulle parti unite da ``|``."""
    if key < 0 or key >= 2**64:
        raise ValueError("key must fit in 8 unsigned bytes")
    msg = "|".join(parts).encode("utf-8")
    return hmac.new(key.to_bytes(8, "big"), msg, hashlib.sha256).digest()


def prf_int(key: int, *parts: str) -> int:
    """Primi 8 byte di ``prf`` come intero big-endian."""
    return int.from_bytes(prf(key, *parts)[:8], "big")


def prf_bit(key: int, *parts: str) -> int:
    """Bit meno significativo dell'ultimo byte di ``prf``."""
    return prf(key, *parts)[-1] & 1


def derive_seed(*parts: object) -> int:
    """Seme in ``[0, 2**31 - 1)``: SHA-256 delle parti (``str``, unite da ``|``), primi 8 byte
    big-endian, modulo ``2**31 - 1``.

    Origine: wm-bench, ``packages/bench-contracts/bench_contracts/seeds.py::derive_seed`` (vedi
    ``PROVENANCE.md``); copiata identica perché la libreria non dipende dal benchmark e le esche
    del registro (§3.10.1) devono coincidere con quelle calcolate lì.
    """
    payload = "|".join(str(p) for p in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") % (2**31 - 1)
