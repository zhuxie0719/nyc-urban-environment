import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def minmax_0_100(series: pd.Series, inverse: bool = False) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").astype(float)
    s = s.replace([np.inf, -np.inf], np.nan)
    s = s.dropna()
    if s.empty:
        return pd.Series([], dtype=float)
    clipped = s.clip(s.quantile(0.01), s.quantile(0.99))
    lo, hi = clipped.min(), clipped.max()
    if lo == hi:
        out = pd.Series(50.0, index=clipped.index)
    else:
        out = (clipped - lo) / (hi - lo) * 100.0
    if inverse:
        out = 100.0 - out
    return out.clip(0, 100)


def facility_score_from_counts(df: pd.DataFrame) -> pd.Series:
    """
    用“设施点位数量”的简单可解释评分（越多越好）。
    - 你后续可扩展为：最近距离/服务半径覆盖等更真实的可达性评分。
    """
    components = []
    for col in ["cooling_site_count", "restroom_count", "fountain_count", "park_count"]:
        if col in df.columns:
            components.append(minmax_0_100(df[col], inverse=False).reindex(df.index))
    if not components:
        return pd.Series(50.0, index=df.index)
    return pd.concat(components, axis=1).mean(axis=1).round(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build score4.csv (environment + facilities scores) by ZIP.")
    parser.add_argument("--env", default="output/environment_by_zip.csv", help="Path to environment_by_zip.csv")
    parser.add_argument(
        "--facilities",
        default="output/facilities_by_zip.csv",
        help="Optional facilities_by_zip.csv (zip_code + *_count columns).",
    )
    parser.add_argument("--out", default="output/score4.csv", help="Output score4.csv path")
    args = parser.parse_args()

    env_path = Path(args.env)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    env = pd.read_csv(env_path, dtype={"zip_code": str})
    env["zip_code"] = env["zip_code"].astype(str).str.extract(r"(\d{5})", expand=False)
    env = env[env["zip_code"].notna()].copy()

    if Path(args.facilities).exists():
        fac = pd.read_csv(args.facilities, dtype={"zip_code": str})
        fac["zip_code"] = fac["zip_code"].astype(str).str.extract(r"(\d{5})", expand=False)
        fac = fac[fac["zip_code"].notna()].copy()
        merged = env.merge(fac, on="zip_code", how="left")
    else:
        merged = env.copy()

    facility_cols = [c for c in ["cooling_site_count", "restroom_count", "fountain_count", "park_count"] if c in merged.columns]
    missing_facility_mask = pd.Series(False, index=merged.index)
    if facility_cols:
        # 这些行通常是“没有设施匹配记录”的数据缺失场景。
        missing_facility_mask = merged[facility_cols].isna().all(axis=1)

    merged["facility_score"] = facility_score_from_counts(merged)
    valid_facility = pd.to_numeric(merged["facility_score"], errors="coerce")
    fill_mean = valid_facility[~missing_facility_mask].dropna().mean()
    if pd.isna(fill_mean):
        fill_mean = valid_facility.dropna().mean()
    if pd.isna(fill_mean):
        fill_mean = 50.0
    merged.loc[missing_facility_mask, "facility_score"] = fill_mean

    score4 = merged[["zip_code", "environment_score", "facility_score"]].copy()
    score4 = score4.rename(columns={"zip_code": "zipcode"})
    score4["environment_score"] = pd.to_numeric(score4["environment_score"], errors="coerce").fillna(50.0).round(2)
    score4["facility_score"] = pd.to_numeric(score4["facility_score"], errors="coerce").fillna(fill_mean).round(2)

    score4.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"score4.csv generated: {out_path} (rows={len(score4)})")
    if not Path(args.facilities).exists():
        print("NOTE: facilities_by_zip.csv not found; facility_score filled by default/available columns only.")


if __name__ == "__main__":
    main()

