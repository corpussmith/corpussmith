"""Premium seam — thesis scaffold export.

Emits a thesis skeleton: chapter outline (intro → lit review → methods →
results → discussion → conclusion), a literature matrix cross-referencing
claims to sources, and chapter-by-chapter bibliographies. Freemium exposes
the contract; the paid build ships the renderer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import require


@dataclass
class ThesisPackResult:
    chapters: List[str] = field(default_factory=list)
    literature_matrix_path: Optional[Path] = None
    bibliography_path: Optional[Path] = None
    output_dir: Optional[Path] = None


def export(
    records: Iterable[Dict[str, Any]],
    *,
    title: str,
    field_: str = "",
    output_dir: Path,
    style: str = "apa",
) -> ThesisPackResult:
    """Render a thesis scaffold from harvested records.

    Premium — raises PremiumNotAvailableError when not activated.
    """
    require("thesis_pack")
    return _render(records, title=title, field_=field_,
                   output_dir=output_dir, style=style)


def _render(records, **kw) -> ThesisPackResult:  # pragma: no cover
    try:
        from corpussmith_premium.thesis_pack import _render as _real
        return _real(records, **kw)
    except ImportError:
        raise NotImplementedError("thesis pack renderer is shipped in the paid build")


__all__ = ["ThesisPackResult", "export"]
