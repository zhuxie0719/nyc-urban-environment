import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import urllib.request


def fetch_socrata_all(dataset_id: str, limit: int = 50000) -> list[dict[str, Any]]:
    """
    NYC Open Data (Socrata) 拉取全量：需要把 $limit/$offset 写成 %24limit/%24offset，否则可能 400。
    """
    base = f"https://data.cityofnewyork.us/resource/{dataset_id}.json"
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        url = f"{base}?%24limit={limit}&%24offset={offset}"
        with urllib.request.urlopen(url) as resp:
            chunk = json.loads(resp.read().decode("utf-8"))
        if not chunk:
            break
        out.extend(chunk)
        if len(chunk) < limit:
            break
        offset += limit
    return out


def safe_float(x: Any) -> float | None:
    try:
        if x is None:
            return None
        v = float(x)
        if math.isfinite(v):
            return v
        return None
    except Exception:
        return None


def extract_point(row: dict[str, Any]) -> tuple[float, float] | None:
    """
    尝试从 Socrata 行中提取 (lon, lat)。
    常见字段：
    - longitude/latitude
    - x/y（很多 NYC 数据用 x=lon, y=lat）
    - location / the_geom（GeoJSON）
    """
    # direct lat/lon
    lon = safe_float(row.get("longitude"))
    lat = safe_float(row.get("latitude"))
    if lon is not None and lat is not None:
        return (lon, lat)

    # x/y
    lon = safe_float(row.get("x"))
    lat = safe_float(row.get("y"))
    if lon is not None and lat is not None:
        # quick sanity: NYC lon/lat ranges
        if -75 < lon < -72 and 40 < lat < 42:
            return (lon, lat)

    # location-like object
    for key in ("location", "the_geom", "geom", "point"):
        obj = row.get(key)
        if isinstance(obj, dict):
            coords = obj.get("coordinates")
            if isinstance(coords, list) and len(coords) >= 2:
                lon = safe_float(coords[0])
                lat = safe_float(coords[1])
                if lon is not None and lat is not None:
                    return (lon, lat)
    return None


def point_in_ring(point: tuple[float, float], ring: list[tuple[float, float]]) -> bool:
    """
    Ray casting. ring: list of (lon,lat), may be closed or not.
    """
    x, y = point
    inside = False
    n = len(ring)
    if n < 3:
        return False
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        intersects = ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-15) + x1)
        if intersects:
            inside = not inside
    return inside


@dataclass
class ZipPoly:
    zip_code: str
    rings: list[list[tuple[float, float]]]
    bbox: tuple[float, float, float, float]  # minx, miny, maxx, maxy


def load_zip_polys(zip_geojson_path: Path) -> list[ZipPoly]:
    data = json.loads(zip_geojson_path.read_text(encoding="utf-8"))
    polys: list[ZipPoly] = []
    for feat in data.get("features", []):
        props = feat.get("properties", {}) or {}
        raw_zip = props.get("postalCode") or props.get("ZIPCODE") or props.get("zip_code") or ""
        zip_code = "".join([c for c in str(raw_zip) if c.isdigit()])[:5]
        if len(zip_code) != 5:
            continue
        geom = feat.get("geometry", {}) or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        rings: list[list[tuple[float, float]]] = []
        if gtype == "Polygon":
            # coords: [ [ [x,y], ... ] , [hole], ...]
            for ring in coords[:1]:
                rings.append([(float(x), float(y)) for x, y in ring])
        elif gtype == "MultiPolygon":
            # coords: [ polygon1, polygon2, ...], each polygon = [outer, holes...]
            for poly in coords:
                if poly and poly[0]:
                    rings.append([(float(x), float(y)) for x, y in poly[0]])
        else:
            continue

        xs: list[float] = []
        ys: list[float] = []
        for ring in rings:
            for x, y in ring:
                xs.append(x)
                ys.append(y)
        if not xs:
            continue
        bbox = (min(xs), min(ys), max(xs), max(ys))
        polys.append(ZipPoly(zip_code=zip_code, rings=rings, bbox=bbox))
    return polys


def lookup_zip(point: tuple[float, float], polys: list[ZipPoly]) -> str | None:
    x, y = point
    for poly in polys:
        minx, miny, maxx, maxy = poly.bbox
        if x < minx or x > maxx or y < miny or y > maxy:
            continue
        for ring in poly.rings:
            if point_in_ring(point, ring):
                return poly.zip_code
    return None


def count_points_by_zip(rows: Iterable[dict[str, Any]], polys: list[ZipPoly]) -> pd.DataFrame:
    counts: dict[str, int] = {}
    missed = 0
    total = 0
    for row in rows:
        total += 1
        pt = extract_point(row)
        if pt is None:
            missed += 1
            continue
        z = lookup_zip(pt, polys)
        if not z:
            missed += 1
            continue
        counts[z] = counts.get(z, 0) + 1
    df = pd.DataFrame({"zip_code": list(counts.keys()), "count": list(counts.values())})
    df["zip_code"] = df["zip_code"].astype(str)
    df = df.sort_values("zip_code").reset_index(drop=True)
    print(f"Mapped points: {total - missed}/{total} (missed={missed})")
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Build facilities_by_zip.csv from NYC Open Data (points -> ZIP).")
    parser.add_argument(
        "--zip-geojson",
        default="frontend/data/nyc_zip_boundaries.geojson",
        help="NYC ZIP boundaries GeoJSON path",
    )
    parser.add_argument("--out", default="output/facilities_by_zip.csv", help="Output CSV path")
    args = parser.parse_args()

    zip_polys = load_zip_polys(Path(args.zip_geojson))
    print(f"ZIP polygons loaded: {len(zip_polys)}")

    datasets = {
        "cooling_site_count": "h2bn-gu9k",  # Cool It! NYC 2020 - Cooling Sites
        "restroom_count": "i7jb-7jku",  # Public Restrooms
        "fountain_count": "qnv7-p7a2",  # NYC Parks Drinking Fountains
    }

    merged: pd.DataFrame | None = None
    for col, dsid in datasets.items():
        rows = fetch_socrata_all(dsid)
        df = count_points_by_zip(rows, zip_polys).rename(columns={"count": col})
        if merged is None:
            merged = df
        else:
            merged = merged.merge(df, on="zip_code", how="outer")

    if merged is None:
        raise RuntimeError("No facilities datasets processed.")

    for c in datasets.keys():
        merged[c] = merged[c].fillna(0).astype(int)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"facilities_by_zip.csv generated: {out} (rows={len(merged)})")


if __name__ == "__main__":
    main()

