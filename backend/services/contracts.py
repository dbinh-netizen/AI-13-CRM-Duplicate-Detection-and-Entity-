_ACCOUNT_CONTRACT = {
    "allowed_entity_types": {"ACCOUNT", "COMPANY", "BRANCH", "SITE"},
    "key_col": "source_key",
    "required_cols": [
        "source_key",
        "source_system",
        "entity_type",
        "legal_name",
        "tax_code",
        "phone",
        "email",
        "address",
    ],
    "optional_rules": {
        "tax_code": r"^\d{10}(-\d{3})?$",
        "phone": r"^(\+84|0)[\d\s\-\.]{8,12}$",
        "email": r"^[\w\.\-]+@[\w\.\-]+\.\w+$",
    },
}

_CONTACT_CONTRACT = {
    "allowed_entity_types": {"CONTACT"},
    "key_col": "source_key",
    "required_cols": [
        "source_key",
        "source_system",
        "entity_type",
        "full_name",
        "phone",
        "email",
    ],
    "optional_rules": {
        "phone": r"^(\+84|0)[\d\s\-\.]{8,12}$",
        "email": r"^[\w\.\-]+@[\w\.\-]+\.\w+$",
    },
}

CSV_CONTRACTS = {
    "ACCOUNT": _ACCOUNT_CONTRACT,
    "CONTACT": _CONTACT_CONTRACT,
    "CRM_A": _ACCOUNT_CONTRACT,
    "CRM_B": _ACCOUNT_CONTRACT,
    "CRM_C": _CONTACT_CONTRACT,
    "CRM_CONTACT": _CONTACT_CONTRACT,
}

SOURCE_SYSTEM_ALIASES = {
    "CRM_A": "CRM_A",
    "ERP_NORTH": "CRM_A",
    "CRM_B": "CRM_B",
    "CRM_SOUTH": "CRM_B",
    "CRM_C": "CRM_C",
    "CRM_CONTACT": "CRM_C",
    "WEB_LEAD": "CRM_C",
    "ZALO_LEAD": "CRM_C",
}

SOURCE_TO_DATASET_TYPE = {
    "ACCOUNT": "ACCOUNT",
    "CONTACT": "CONTACT",
    "CRM_A": "ACCOUNT",
    "ERP_NORTH": "ACCOUNT",
    "CRM_B": "ACCOUNT",
    "CRM_SOUTH": "ACCOUNT",
    "CRM_C": "CONTACT",
    "CRM_CONTACT": "CONTACT",
    "WEB_LEAD": "CONTACT",
    "ZALO_LEAD": "CONTACT",
}


def resolve_canonical_source_code(raw_source_system: str, fallback: str = "CRM_A") -> str:
    """Chuẩn hóa mã hệ thống nguồn về CRM_A / CRM_B / CRM_C."""
    cleaned = (raw_source_system or "").strip().upper()
    if not cleaned:
        return fallback
    return SOURCE_SYSTEM_ALIASES.get(cleaned, cleaned)