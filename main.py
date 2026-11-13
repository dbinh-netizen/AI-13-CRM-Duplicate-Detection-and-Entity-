from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from backend.database import Base, engine
from backend.api.routes import router as api_router

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="CRM Duplicate Detection & Entity Resolution",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

@app.get("/")
def serve_dashboard():
    ui_path = Path("frontend/index.html")
    if ui_path.exists():
        return FileResponse(ui_path)
    return {"message": "Server đang chạy. Mở /docs để xem API."}

@app.get("/review")
def serve_duplicate_review():
    review_path = Path("frontend/duplicate_review.html")
    if review_path.exists() and review_path.stat().st_size > 0:
        return FileResponse(review_path)
    return FileResponse(Path("frontend/index.html"))
