import os
from pathlib import Path
from dotenv import load_dotenv

# Tải biến môi trường từ file .env nếu có
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Môi trường chạy ứng dụng (dev / staging / prod)
APP_ENV: str = os.getenv("APP_ENV", "dev")

# Cấu hình kết nối cơ sở dữ liệu
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./data/songnhat_crm.db")

# Ngưỡng thuật toán so khớp & giới hạn số lượng cặp ứng viên
CANDIDATE_CEILING: int = int(os.getenv("CANDIDATE_CEILING", "200000"))
SUSPECTED_THRESHOLD: float = float(os.getenv("SUSPECTED_THRESHOLD", "65.0"))
HIGH_CONFIDENCE_THRESHOLD: float = float(os.getenv("HIGH_CONFIDENCE_THRESHOLD", "85.0"))

# Cấu hình bảo mật & JWT Token
SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-songnhat-crm-2026-phase2")
ALGORITHM: str = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))
