"""Helpers to normalize Azure Document Intelligence polygons into CAN-SR/Grobid-style boxes.

Frontend (PDFBoundingBoxViewer) expects per-page boxes with fields:
  { page, x, y, width, height }

Grobid coords are in TEI pixel space from the original PDF rendering.
Azure DI returns polygons in page units (typically "inch" or "pixel").

We normalize by:
  1) Converting Azure units to pixel space when possible (inch->72dpi pixels).
  2) Converting polygon -> axis-aligned bounding rect.

This is best-effort and is intended for highlighting tables/figures similar
to sentence highlighting.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _page_meta_by_number(pages_meta: Any) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    if not isinstance(pages_meta, list):
        return out
    for p in pages_meta:
        if not isinstance(p, dict):
            continue
        num = p.get("pageNumber") or p.get("page_number")
        try:
            num_i = int(num)
        except Exception:
            continue
        out[num_i] = p
    return out


def _unit_to_scale(unit: Optional[str]) -> float:
    """Return multiplier to convert unit coordinates into ~PDF pixels.

    Azure DI commonly reports:
      - unit == 'inch'
      - unit == 'pixel'
      - unit == None

    We assume PDF coordinate space is 72 dpi points.
    """

    if not unit:
        return 1.0
    u = str(unit).strip().lower()
    if u in ("pixel", "pixels", "px"):
        return 1.0
    if u in ("inch", "in"):
        return 72.0
    # Unknown units: do not scale.
    return 1.0


def polygon_to_bbox(polygon: Any) -> Optional[Tuple[float, float, float, float]]:
    """Convert Azure polygon [x1,y1,x2,y2,...] to (minx, miny, maxx, maxy)."""
    if not isinstance(polygon, list) or len(polygon) < 8:
        return None
    try:
        xs = [float(polygon[i]) for i in range(0, len(polygon), 2)]
        ys = [float(polygon[i]) for i in range(1, len(polygon), 2)]
    except Exception:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def normalize_bounding_regions_to_boxes(
    bounding_regions: Any,
    pages_meta: Any,
) -> List[Dict[str, Any]]:
    """Normalize Azure boundingRegions -> list of {page,x,y,width,height}.

    bounding_regions supports either:
      - [{'pageNumber'|'page_number': 1, 'polygon': [...]}, ...]
      - [{'page_number': 1, 'polygon': [...]}, ...]
    """
    out: List[Dict[str, Any]] = []
    if not isinstance(bounding_regions, list):
        return out

    pm = _page_meta_by_number(pages_meta)

    for region in bounding_regions:
        if not isinstance(region, dict):
            continue

        page = region.get("pageNumber")
        if page is None:
            page = region.get("page_number")
        try:
            page_i = int(page)
        except Exception:
            continue

        poly = region.get("polygon")
        bbox = polygon_to_bbox(poly)
        if not bbox:
            continue

        unit = None
        if page_i in pm:
            unit = pm[page_i].get("unit")

        s = _unit_to_scale(unit)
        minx, miny, maxx, maxy = bbox
        minx *= s
        miny *= s
        maxx *= s
        maxy *= s

        out.append(
            {
                "page": page_i,
                "x": minx,
                "y": miny,
                "width": max(0.0, maxx - minx),
                "height": max(0.0, maxy - miny),
            }
        )

    return out
