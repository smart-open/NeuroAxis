"""Spec version chain (8.2 spec_version DDL semantics).

W2 ships the in-memory/JSON-file chain; the PG-backed store plugs into the
same interface once the persistence layer lands. The chain guarantees:
monotonic seq per project, immutable yaml text, sha256 integrity.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field


class VersionConflict(ValueError):
    """Sequence collision or tampered history."""


@dataclass(frozen=True)
class SpecVersion:
    project_code: str
    seq: int
    yaml_text: str
    yaml_sha256: str
    author: str                      # "human" / "agent:debugger"
    created_at: float                # wall clock ok here: bookkeeping, not sim
    approved_by: str | None = None


@dataclass
class SpecVersionChain:
    """Append-only version list for one project (per-process store for now)."""

    project_code: str
    _versions: list[SpecVersion] = field(default_factory=list)

    def commit(self, yaml_text: str, author: str) -> SpecVersion:
        digest = hashlib.sha256(yaml_text.encode("utf-8")).hexdigest()
        version = SpecVersion(
            project_code=self.project_code,
            seq=len(self._versions) + 1,
            yaml_text=yaml_text,
            yaml_sha256=digest,
            author=author,
            created_at=time.time(),
        )
        self._versions.append(version)
        return version

    def approve(self, seq: int, by_user: str) -> SpecVersion:
        version = self.get(seq)
        updated = SpecVersion(
            project_code=version.project_code, seq=version.seq,
            yaml_text=version.yaml_text, yaml_sha256=version.yaml_sha256,
            author=version.author, created_at=version.created_at,
            approved_by=by_user,
        )
        self._versions[seq - 1] = updated
        return updated

    def get(self, seq: int) -> SpecVersion:
        if not 1 <= seq <= len(self._versions):
            raise VersionConflict(f"seq {seq} out of range 1..{len(self._versions)}")
        return self._versions[seq - 1]

    def latest(self) -> SpecVersion:
        if not self._versions:
            raise VersionConflict("no versions committed")
        return self._versions[-1]

    def all(self) -> tuple[SpecVersion, ...]:
        return tuple(self._versions)

    def verify_integrity(self) -> bool:
        """Recompute every sha256; catches accidental text mutation."""
        return all(
            version.yaml_sha256 == hashlib.sha256(version.yaml_text.encode("utf-8")).hexdigest()
            for version in self._versions
        )

    def to_json(self) -> str:
        payload = [version.__dict__ for version in self._versions]
        return json.dumps(payload, ensure_ascii=False, indent=2)
