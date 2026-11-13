"""[PHẦN VIỆC: CHUẨN HÓA DỮ LIỆU TIẾNG VIỆT, SĐT, MÃ SỐ THUẾ]"""
import re
import unicodedata

def remove_accents(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFD", str(text).strip().lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.replace("đ", "d")

def normalize_phone_vn(phone: str) -> str:
    digits = re.sub(r"[^\d+]", "", str(phone or ""))
    return re.sub(r"^\+?84", "0", digits)

def parse_tax_code(tax_code: str) -> dict:
    raw = str(tax_code or "").strip()
    parts = raw.split("-")
    return {
        "raw": raw,
        "root": parts[0] if parts else "",
        "branch": parts[1] if len(parts) > 1 else ""
    }

def enrich_normalized_fields(rec: dict) -> dict:
    raw_name = rec.get("legal_name") or rec.get("full_name") or ""
    tax = parse_tax_code(rec.get("tax_code", ""))
    return {
        **rec,
        "norm_name_accent": str(raw_name).strip().lower(),
        "norm_name_no_accent": remove_accents(raw_name),
        "norm_phone": normalize_phone_vn(rec.get("phone", "")),
        "norm_email": str(rec.get("email") or "").strip().lower(),
        "tax_root": tax["root"],
        "tax_branch": tax["branch"]
    }
