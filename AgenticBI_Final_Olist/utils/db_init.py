from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import text

from utils.data_clean import CleanReport, clean_table
from utils.db import build_mysql_engine, ensure_database_exists
from utils.settings import RAW_DATA_DIR


DATASET_FILES = {
    "customers": "olist_customers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "product_category_name_translation": "product_category_name_translation.csv",
}


TABLE_RENAMES = {
    "order_payments": "payments",
    "order_reviews": "order_reviews",
}


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)


def _print_clean_report(report: CleanReport) -> None:
    dropped = report.rows_dropped
    if dropped or report.actions:
        print(f"  cleaned {report.table}: {report.rows_before:,} -> {report.rows_after:,} rows")
        for action in report.actions:
            print(f"    - {action}")
    else:
        print(f"  cleaned {report.table}: {report.rows_after:,} rows (no changes)")


def load_csvs_to_mysql() -> list[CleanReport]:
    ensure_database_exists()
    engine = build_mysql_engine()

    if not RAW_DATA_DIR.exists():
        raise FileNotFoundError(
            f"raw data directory not found: {RAW_DATA_DIR}. Put Olist CSVs into data/raw/"
        )

    with engine.begin() as conn:
        conn.execute(text("SET SESSION sql_mode=''"))

    reports: list[CleanReport] = []

    for key, filename in DATASET_FILES.items():
        csv_path = RAW_DATA_DIR / filename
        if not csv_path.exists():
            raise FileNotFoundError(f"missing CSV: {csv_path}")

        raw_df = _read_csv(csv_path)
        df, report = clean_table(key, raw_df)
        reports.append(report)
        table_name = TABLE_RENAMES.get(key, key)

        df.to_sql(table_name, engine, if_exists="replace", index=False, chunksize=5000, method="multi")
        print(f"loaded {table_name}: {len(df):,} rows")
        _print_clean_report(report)

    # basic indexes for joins
    with engine.begin() as conn:
        index_ddls = [
            "CREATE INDEX idx_orders_order_id ON orders(order_id)",
            "CREATE INDEX idx_orders_customer_id ON orders(customer_id)",
            "CREATE INDEX idx_orders_purchase_ts ON orders(order_purchase_timestamp)",
            "CREATE INDEX idx_items_order_id ON order_items(order_id)",
            "CREATE INDEX idx_items_product_id ON order_items(product_id)",
            "CREATE INDEX idx_items_seller_id ON order_items(seller_id)",
            "CREATE INDEX idx_payments_order_id ON payments(order_id)",
            "CREATE INDEX idx_reviews_order_id ON order_reviews(order_id)",
            "CREATE INDEX idx_customers_customer_id ON customers(customer_id)",
            "CREATE INDEX idx_customers_zip_prefix ON customers(customer_zip_code_prefix)",
            "CREATE INDEX idx_customers_state ON customers(customer_state)",
            "CREATE INDEX idx_translation_cat_pt ON product_category_name_translation(product_category_name)",
            "CREATE INDEX idx_geolocation_zip_prefix ON geolocation(geolocation_zip_code_prefix)",
        ]
        for ddl in index_ddls:
            try:
                conn.execute(text(ddl))
            except Exception:
                pass

    return reports


def main() -> None:
    print("=== Olist data init (load + clean + index) ===")
    load_csvs_to_mysql()
    print("=== done ===")


if __name__ == "__main__":
    main()
