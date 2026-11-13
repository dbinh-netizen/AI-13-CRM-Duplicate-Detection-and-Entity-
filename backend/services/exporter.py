"""[PHẦN VIỆC: XUẤT BẢNG ĐỊNH DANH CHUẨN CROSSWALK CSV]"""
import io
import csv

def export_crosswalk_csv(candidates: list[dict]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["canonical_id", "left_source_key", "right_source_key", "category", "similarity_score"])
    for idx, c in enumerate(candidates, start=1):
        writer.writerow([f"CAN-{1000+idx}", c["left_source_key"], c["right_source_key"], c["proposed_category"], c["similarity_score"]])
    return output.getvalue()
