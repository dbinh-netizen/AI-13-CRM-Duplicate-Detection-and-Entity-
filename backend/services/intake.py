"""[PHẦN VIỆC: ĐỌC & KIỂM TRA DỮ LIỆU ĐẦU VÀO CSV]"""
from pathlib import Path
import pandas as pd

CSV_DIR = Path("data/sample_csv")

def load_all_csv_records() -> list[dict]:
    records = []
    for file_name in ["accounts_source_a.csv", "accounts_source_b.csv", "contacts_source.csv"]:
        path = CSV_DIR / file_name
        if path.exists():
            df = pd.read_csv(path, dtype=str).fillna("")
            for row_number, record in enumerate(df.to_dict(orient="records"), start=2):
                record["record_id"] = f"{file_name}:{row_number}"
                records.append(record)
    return records
