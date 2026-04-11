import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


ZIP_CANDIDATES = [
    "zip_code",
    "zipcode",
    "zip",
    "zip_new",
    "zip_original",
    "incident_zip",
    "incident zip",
    "postal_code",
    "school zip",
]

DATE_CANDIDATES = ["date", "created_date", "created date", "start_date", "start date", "timestamp"]


def find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lowered = {c.lower(): c for c in df.columns}
    for key in candidates:
        if key in lowered:
            return lowered[key]
    return None


def clean_zip(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.extract(r"(\d{5})", expand=False)
    return s


def normalize_borough_name(value: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text == "nan":
        return None
    if "manhattan" in text:
        return "manhattan"
    if "brooklyn" in text:
        return "brooklyn"
    if "queens" in text:
        return "queens"
    if "bronx" in text:
        return "bronx"
    if "staten" in text:
        return "staten island"
    return None


def minmax_score(series: pd.Series, inverse: bool = False) -> pd.Series:
    s = series.astype(float)
    s = s.clip(s.quantile(0.01), s.quantile(0.99))
    lo, hi = s.min(), s.max()
    if pd.isna(lo) or pd.isna(hi) or lo == hi:
        score = pd.Series(50.0, index=s.index)
    else:
        score = (s - lo) / (hi - lo) * 100.0
    if inverse:
        score = 100.0 - score
    return score.clip(0, 100)


def aggregate_air_quality(air_path: Path) -> pd.DataFrame:
    df = pd.read_csv(air_path)
    zip_col = find_col(df, ZIP_CANDIDATES)
    if zip_col:
        df["zip_code"] = clean_zip(df[zip_col])
        df = df[df["zip_code"].notna()].copy()

        metric_map = {
            "pm25": ["pm25", "pm_25", "pm2.5"],
            "no2": ["no2", "nitrogen_dioxide"],
            "o3": ["o3", "ozone"],
        }

        selected = {}
        lowered = {c.lower(): c for c in df.columns}
        for metric, candidates in metric_map.items():
            for c in candidates:
                if c in lowered:
                    selected[metric] = lowered[c]
                    break

        if not selected:
            numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
            if not numeric_cols:
                raise ValueError("空气质量数据没有可用数值字段。")
            selected["pollution_proxy"] = numeric_cols[0]

        grouped = df.groupby("zip_code", as_index=False)[list(selected.values())].mean()

        if "pollution_proxy" in selected:
            pollution = grouped[selected["pollution_proxy"]]
        else:
            pollution = (
                grouped[selected["pm25"]] * 0.40
                + grouped[selected["no2"]] * 0.35
                + grouped[selected["o3"]] * 0.25
            )

        out = pd.DataFrame({"zip_code": grouped["zip_code"], "air_pollution_index": pollution})
        out["air_quality_score"] = minmax_score(out["air_pollution_index"], inverse=True).round(2)
        return out[["zip_code", "air_quality_score"]]

    # Fallback: NYC official air data often has Borough/CD/UHF but not zip.
    geo_type_col = find_col(df, ["geo type name", "geo_type_name"])
    geo_place_col = find_col(df, ["geo place name", "geo_place_name"])
    value_col = find_col(df, ["data value", "data_value", "value"])
    if not (geo_type_col and geo_place_col and value_col):
        raise ValueError("空气质量数据既没有 zip，也缺少 Geo Type/Place/Data Value 字段。")

    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    df = df[df[value_col].notna()].copy()

    borough_df = df[df[geo_type_col].astype(str).str.lower() == "borough"].copy()
    if borough_df.empty:
        raise ValueError("空气质量数据未找到 Borough 级别记录，无法映射到 zip。")

    name_col = find_col(borough_df, ["name", "indicator", "indicator name"])
    if name_col:
        n = borough_df[name_col].astype(str).str.lower()
        pm = borough_df[n.str.contains(r"pm|particulate", na=False)].groupby(geo_place_col)[value_col].mean()
        no2 = borough_df[n.str.contains(r"\bno2\b|nitrogen", na=False)].groupby(geo_place_col)[value_col].mean()
        o3 = borough_df[n.str.contains(r"\bo3\b|ozone", na=False)].groupby(geo_place_col)[value_col].mean()
        base = borough_df.groupby(geo_place_col)[value_col].mean().rename("base")
        merged = pd.DataFrame(base)
        merged["pm"] = pm
        merged["no2"] = no2
        merged["o3"] = o3
        merged["pollution"] = (
            0.40 * merged["pm"].fillna(merged["base"])
            + 0.35 * merged["no2"].fillna(merged["base"])
            + 0.25 * merged["o3"].fillna(merged["base"])
        )
        borough_score = merged["pollution"]
    else:
        borough_score = borough_df.groupby(geo_place_col)[value_col].mean()

    out = borough_score.reset_index()
    out.columns = ["borough_name", "air_pollution_index"]
    out["borough_key"] = out["borough_name"].map(normalize_borough_name)
    out = out[out["borough_key"].notna()].copy()
    out["air_quality_score"] = minmax_score(out["air_pollution_index"], inverse=True).round(2)
    return out[["borough_key", "air_quality_score"]]


def aggregate_noise(noise_path: Path, months: int | None = 12) -> pd.DataFrame:
    df = pd.read_csv(noise_path, low_memory=False)

    zip_col = find_col(df, ZIP_CANDIDATES)
    if not zip_col:
        raise ValueError("311 数据中未找到 zip 字段。")
    df["zip_code"] = clean_zip(df[zip_col])
    df = df[df["zip_code"].notna()].copy()

    complaint_type_col = find_col(df, ["complaint_type", "complaint type"])
    descriptor_col = find_col(df, ["descriptor"])
    if complaint_type_col:
        mask = df[complaint_type_col].astype(str).str.contains("noise", case=False, na=False)
        df = df[mask].copy()
    elif descriptor_col:
        # Fallback for datasets without complaint type.
        mask = df[descriptor_col].astype(str).str.contains("noise|loud", case=False, na=False)
        df = df[mask].copy()

    date_col = find_col(df, DATE_CANDIDATES)
    if months and date_col:
        dt = pd.to_datetime(df[date_col], errors="coerce")
        cutoff = dt.max() - pd.DateOffset(months=months)
        df = df[dt >= cutoff].copy()

    noise_count = df.groupby("zip_code", as_index=False).size().rename(columns={"size": "noise_count"})
    noise_count["noise_score"] = minmax_score(noise_count["noise_count"], inverse=True).round(2)
    borough_col = find_col(df, ["borough", "city"])
    if borough_col:
        z2b = df[["zip_code", borough_col]].copy()
        z2b["borough_key"] = z2b[borough_col].map(normalize_borough_name)
        z2b = z2b[z2b["borough_key"].notna()].copy()
        z2b = z2b.groupby("zip_code")["borough_key"].agg(lambda x: x.mode().iloc[0] if not x.mode().empty else x.iloc[0]).reset_index()
        noise_count = noise_count.merge(z2b, on="zip_code", how="left")
    else:
        noise_count["borough_key"] = None
    return noise_count[["zip_code", "noise_score", "borough_key"]]


def aggregate_green(tree_path: Path) -> pd.DataFrame:
    df = pd.read_csv(tree_path, low_memory=False)
    zip_col = find_col(df, ZIP_CANDIDATES)
    if not zip_col:
        raise ValueError("Tree Census 数据中未找到 zip 字段。")

    df["zip_code"] = clean_zip(df[zip_col])
    df = df[df["zip_code"].notna()].copy()

    tree_count = df.groupby("zip_code", as_index=False).size().rename(columns={"size": "tree_count"})
    tree_count["green_score"] = minmax_score(tree_count["tree_count"], inverse=False).round(2)
    borough_col = find_col(df, ["borough"])
    if borough_col:
        z2b = df[["zip_code", borough_col]].copy()
        z2b["borough_key"] = z2b[borough_col].map(normalize_borough_name)
        z2b = z2b[z2b["borough_key"].notna()].copy()
        z2b = z2b.groupby("zip_code")["borough_key"].agg(lambda x: x.mode().iloc[0] if not x.mode().empty else x.iloc[0]).reset_index()
        tree_count = tree_count.merge(z2b, on="zip_code", how="left")
    else:
        tree_count["borough_key"] = None
    return tree_count[["zip_code", "green_score", "borough_key"]]


def build_environment_table(air_df: pd.DataFrame, noise_df: pd.DataFrame, green_df: pd.DataFrame) -> pd.DataFrame:
    merged = noise_df.merge(green_df, on="zip_code", how="outer", suffixes=("_noise", "_green"))
    merged["borough_key"] = merged["borough_key_noise"].fillna(merged["borough_key_green"])
    merged = merged.drop(columns=["borough_key_noise", "borough_key_green"])

    if "zip_code" in air_df.columns:
        merged = merged.merge(air_df, on="zip_code", how="left")
    else:
        merged = merged.merge(air_df, on="borough_key", how="left")

    for col in ["air_quality_score", "noise_score", "green_score"]:
        merged[col] = merged[col].fillna(merged[col].median()).fillna(50.0)

    merged["environment_score"] = (
        0.45 * merged["air_quality_score"]
        + 0.35 * merged["noise_score"]
        + 0.20 * merged["green_score"]
    ).round(2)

    merged = merged.sort_values("zip_code").reset_index(drop=True)
    return merged[["zip_code", "air_quality_score", "noise_score", "green_score", "environment_score"]]


def export_final_json(df: pd.DataFrame, output_path: Path) -> None:
    records = []
    for row in df.to_dict(orient="records"):
        records.append(
            {
                "zip_code": row["zip_code"],
                "environment": {
                    "environment_score": row["environment_score"],
                    "air_quality_score": row["air_quality_score"],
                    "noise_score": row["noise_score"],
                    "green_score": row["green_score"],
                },
            }
        )
    output_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build NYC environment scores by zip code.")
    parser.add_argument("--air", default="Air_Quality.csv", help="Path to air quality csv")
    parser.add_argument("--noise311", default="NYC311data.csv", help="Path to 311 csv")
    parser.add_argument("--tree", default="new_york_tree_census_1995.csv", help="Path to tree census csv")
    parser.add_argument("--out-csv", default="output/environment_by_zip.csv", help="Output csv path")
    parser.add_argument("--out-json", default="output/final_data.environment.json", help="Output json path")
    parser.add_argument("--months", type=int, default=12, help="311 trailing months window")
    args = parser.parse_args()

    out_csv = Path(args.out_csv)
    out_json = Path(args.out_json)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)

    air_df = aggregate_air_quality(Path(args.air))
    noise_df = aggregate_noise(Path(args.noise311), months=args.months)
    green_df = aggregate_green(Path(args.tree))

    final_df = build_environment_table(air_df, noise_df, green_df)
    final_df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    export_final_json(final_df, out_json)

    print(f"CSV generated: {out_csv}")
    print(f"JSON generated: {out_json}")
    print(f"zip_code count: {len(final_df)}")


if __name__ == "__main__":
    main()
