from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import pandas as pd


@dataclass
class CleanReport:
    table: str
    rows_before: int
    rows_after: int
    actions: list[str] = field(default_factory=list)

    @property
    def rows_dropped(self) -> int:
        return self.rows_before - self.rows_after


def _parse_timestamps(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for col in cols:
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")
    return out


def _strip_object_cols(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.select_dtypes(include=["object"]).columns:
        out[col] = out[col].astype(str).str.strip()
        out[col] = out[col].replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    return out


def clean_orders(df: pd.DataFrame) -> tuple[pd.DataFrame, CleanReport]:
    report = CleanReport("orders", len(df), len(df))
    out = _strip_object_cols(df)

    ts_cols = [
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ]
    out = _parse_timestamps(out, ts_cols)

    dup_cnt = out.duplicated(subset=["order_id"], keep="first").sum()
    if dup_cnt:
        out = out.drop_duplicates(subset=["order_id"], keep="first")
        report.actions.append(f"removed {dup_cnt} duplicate order_id rows")

    invalid_status = out["order_status"].isna().sum() if "order_status" in out.columns else 0
    if invalid_status:
        out = out[out["order_status"].notna()]
        report.actions.append(f"dropped {invalid_status} rows with null order_status")

    report.rows_after = len(out)
    return out, report


def clean_order_items(df: pd.DataFrame) -> tuple[pd.DataFrame, CleanReport]:
    report = CleanReport("order_items", len(df), len(df))
    out = _strip_object_cols(df)
    out = _parse_timestamps(out, ["shipping_limit_date"])

    dup_cnt = out.duplicated(subset=["order_id", "order_item_id"], keep="first").sum()
    if dup_cnt:
        out = out.drop_duplicates(subset=["order_id", "order_item_id"], keep="first")
        report.actions.append(f"removed {dup_cnt} duplicate (order_id, order_item_id) rows")

    for col in ("price", "freight_value"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
            null_cnt = out[col].isna().sum()
            if null_cnt:
                out = out[out[col].notna()]
                report.actions.append(f"dropped {null_cnt} rows with null {col}")

    report.rows_after = len(out)
    return out, report


def clean_products(df: pd.DataFrame) -> tuple[pd.DataFrame, CleanReport]:
    report = CleanReport("products", len(df), len(df))
    out = _strip_object_cols(df)

    dup_cnt = out.duplicated(subset=["product_id"], keep="first").sum()
    if dup_cnt:
        out = out.drop_duplicates(subset=["product_id"], keep="first")
        report.actions.append(f"removed {dup_cnt} duplicate product_id rows")

    if "product_category_name" in out.columns:
        missing_cat = out["product_category_name"].isna().sum()
        if missing_cat:
            out["product_category_name"] = out["product_category_name"].fillna("unknown")
            report.actions.append(f"filled {missing_cat} null product_category_name with 'unknown'")

    numeric_cols = [
        "product_name_length",
        "product_description_length",
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    ]
    for col in numeric_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    report.rows_after = len(out)
    return out, report


def clean_customers(df: pd.DataFrame) -> tuple[pd.DataFrame, CleanReport]:
    report = CleanReport("customers", len(df), len(df))
    out = _strip_object_cols(df)

    dup_cnt = out.duplicated(subset=["customer_id"], keep="first").sum()
    if dup_cnt:
        out = out.drop_duplicates(subset=["customer_id"], keep="first")
        report.actions.append(f"removed {dup_cnt} duplicate customer_id rows")

    if "customer_state" in out.columns:
        out["customer_state"] = out["customer_state"].astype(str).str.upper().str.strip()
        out.loc[out["customer_state"].isin(["", "NAN", "NONE"]), "customer_state"] = pd.NA
        null_state = out["customer_state"].isna().sum()
        if null_state:
            out = out[out["customer_state"].notna()]
            report.actions.append(f"dropped {null_state} rows with invalid customer_state")

    if "customer_zip_code_prefix" in out.columns:
        out["customer_zip_code_prefix"] = pd.to_numeric(
            out["customer_zip_code_prefix"], errors="coerce"
        ).astype("Int64")

    report.rows_after = len(out)
    return out, report


def clean_sellers(df: pd.DataFrame) -> tuple[pd.DataFrame, CleanReport]:
    report = CleanReport("sellers", len(df), len(df))
    out = _strip_object_cols(df)

    dup_cnt = out.duplicated(subset=["seller_id"], keep="first").sum()
    if dup_cnt:
        out = out.drop_duplicates(subset=["seller_id"], keep="first")
        report.actions.append(f"removed {dup_cnt} duplicate seller_id rows")

    if "seller_state" in out.columns:
        out["seller_state"] = out["seller_state"].astype(str).str.upper().str.strip()

    if "seller_zip_code_prefix" in out.columns:
        out["seller_zip_code_prefix"] = pd.to_numeric(
            out["seller_zip_code_prefix"], errors="coerce"
        ).astype("Int64")

    report.rows_after = len(out)
    return out, report


def clean_payments(df: pd.DataFrame) -> tuple[pd.DataFrame, CleanReport]:
    report = CleanReport("payments", len(df), len(df))
    out = _strip_object_cols(df)

    for col in ("payment_installments", "payment_value"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    null_value = out["payment_value"].isna().sum() if "payment_value" in out.columns else 0
    if null_value:
        out = out[out["payment_value"].notna()]
        report.actions.append(f"dropped {null_value} rows with null payment_value")

    if "payment_type" in out.columns:
        out["payment_type"] = out["payment_type"].astype(str).str.lower().str.strip()

    report.rows_after = len(out)
    return out, report


def clean_order_reviews(df: pd.DataFrame) -> tuple[pd.DataFrame, CleanReport]:
    report = CleanReport("order_reviews", len(df), len(df))
    out = _strip_object_cols(df)
    out = _parse_timestamps(out, ["review_creation_date", "review_answer_timestamp"])

    dup_cnt = out.duplicated(subset=["order_id"], keep="first").sum()
    if dup_cnt:
        out = out.drop_duplicates(subset=["order_id"], keep="first")
        report.actions.append(f"removed {dup_cnt} duplicate order_id review rows")

    if "review_score" in out.columns:
        out["review_score"] = pd.to_numeric(out["review_score"], errors="coerce")
        invalid = (~out["review_score"].between(1, 5, inclusive="both")).sum()
        if invalid:
            out = out[out["review_score"].between(1, 5, inclusive="both")]
            report.actions.append(f"dropped {invalid} rows with review_score outside 1-5")

    for col in ("review_comment_title", "review_comment_message"):
        if col in out.columns:
            out[col] = out[col].fillna("")

    report.rows_after = len(out)
    return out, report


def clean_geolocation(df: pd.DataFrame) -> tuple[pd.DataFrame, CleanReport]:
    report = CleanReport("geolocation", len(df), len(df))
    out = _strip_object_cols(df)

    for col in ("geolocation_lat", "geolocation_lng"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    invalid_geo = out["geolocation_lat"].isna().sum() if "geolocation_lat" in out.columns else 0
    if invalid_geo:
        out = out[out["geolocation_lat"].notna() & out["geolocation_lng"].notna()]
        report.actions.append(f"dropped {invalid_geo} rows with invalid lat/lng")

    if "geolocation_state" in out.columns:
        out["geolocation_state"] = out["geolocation_state"].astype(str).str.upper().str.strip()

    # aggregate duplicate zip prefixes to reduce join explosion at query time
    before = len(out)
    out = (
        out.groupby("geolocation_zip_code_prefix", as_index=False)
        .agg(
            geolocation_lat=("geolocation_lat", "mean"),
            geolocation_lng=("geolocation_lng", "mean"),
            geolocation_city=("geolocation_city", "first"),
            geolocation_state=("geolocation_state", "first"),
        )
    )
    if len(out) < before:
        report.actions.append(
            f"aggregated geolocation from {before:,} to {len(out):,} rows by zip prefix"
        )

    report.rows_after = len(out)
    return out, report


def clean_category_translation(df: pd.DataFrame) -> tuple[pd.DataFrame, CleanReport]:
    report = CleanReport("product_category_name_translation", len(df), len(df))
    out = _strip_object_cols(df)

    dup_cnt = out.duplicated(subset=["product_category_name"], keep="first").sum()
    if dup_cnt:
        out = out.drop_duplicates(subset=["product_category_name"], keep="first")
        report.actions.append(f"removed {dup_cnt} duplicate Portuguese category rows")

    if "product_category_name_english" in out.columns:
        missing_en = out["product_category_name_english"].isna().sum()
        if missing_en:
            out["product_category_name_english"] = out["product_category_name_english"].fillna(
                out["product_category_name"]
            )
            report.actions.append(
                f"filled {missing_en} missing English names with Portuguese fallback"
            )

    report.rows_after = len(out)
    return out, report


CLEANERS: dict[str, Callable[[pd.DataFrame], tuple[pd.DataFrame, CleanReport]]] = {
    "orders": clean_orders,
    "order_items": clean_order_items,
    "products": clean_products,
    "customers": clean_customers,
    "sellers": clean_sellers,
    "payments": clean_payments,
    "order_reviews": clean_order_reviews,
    "geolocation": clean_geolocation,
    "product_category_name_translation": clean_category_translation,
}


def clean_table(table_key: str, df: pd.DataFrame) -> tuple[pd.DataFrame, CleanReport]:
    """
    Clean a single Olist table before MySQL load.

    Args:
        table_key: key from DATASET_FILES (e.g. 'orders', 'order_payments')
        df: raw dataframe read from CSV
    """
    cleaner_key = {
        "order_payments": "payments",
        "order_reviews": "order_reviews",
    }.get(table_key, table_key)

    cleaner = CLEANERS.get(cleaner_key)
    if cleaner is None:
        report = CleanReport(table_key, len(df), len(df), actions=["no cleaner defined, passthrough"])
        return df, report
    return cleaner(df)


def clean_all(dfs: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], list[CleanReport]]:
    cleaned: dict[str, pd.DataFrame] = {}
    reports: list[CleanReport] = []
    for key, df in dfs.items():
        cleaned_df, report = clean_table(key, df)
        cleaned[key] = cleaned_df
        reports.append(report)
    return cleaned, reports
