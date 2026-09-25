"""
Chain verification — walk the audit log from oldest to newest and recompute
every hash. Returns `(True, [])` if intact, otherwise `(False, [broken_ids])`.
"""
from __future__ import annotations

from typing import List, Tuple

from .models import AuditLog


def verify_chain() -> Tuple[bool, List[str]]:
    """Verify the integrity of the whole audit chain.

    NB: la première entrée d'une chaîne saine a prev_hash = "0" * 64
    (défaut du modèle), PAS une chaîne vide.
    """
    rows = list(AuditLog.objects.order_by("id"))
    prev_hash = "0" * 64
    broken: list[str] = []
    for row in rows:
        # Check that the row's prev_hash matches the previous row's hash.
        if row.prev_hash != prev_hash:
            broken.append(str(row.id))
        # Recompute the hash from the row's own data.
        recomputed = row.compute_hash()
        if recomputed != row.hash:
            broken.append(str(row.id))
        prev_hash = row.hash
    return (len(broken) == 0, broken)


__all__ = ["verify_chain"]
