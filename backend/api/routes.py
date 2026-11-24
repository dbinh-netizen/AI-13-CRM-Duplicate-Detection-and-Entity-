from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from backend.schemas import ReviewDecisionRequest
from backend.services.intake import load_all_csv_records
from backend.services.matcher import generate_candidates
from backend.services.resolver import verify_independent_approver
from backend.services.exporter import export_crosswalk_csv
from backend.api.review_routes import router as review_router
from backend.api.canonical_routes import router as canonical_router
from backend.api.candidate_routes import router as candidate_router

router = APIRouter(prefix="/api", tags=["CRM Entity Resolution API"])
router.include_router(review_router)
router.include_router(canonical_router)
router.include_router(candidate_router)

@router.get("/records")
def get_all_source_records():
    records = load_all_csv_records()
    return {"total": len(records), "records": records}


@router.post("/approve")
def approve_decision(payload: ReviewDecisionRequest):
    if not verify_independent_approver(payload.steward_user, payload.approver_user):
        raise HTTPException(
            status_code=400,
            detail="Người đề xuất (Steward) không được phép tự phê duyệt (Approver)!"
        )
    return {
        "status": "APPROVED",
        "canonical_id": f"CAN-{payload.left_source_key}",
        "decision_category": payload.decision_category,
        "approved_by": payload.approver_user
    }

@router.get("/export/crosswalk.csv", response_class=PlainTextResponse)
def download_crosswalk_csv():
    records = load_all_csv_records()
    result = generate_candidates(records)
    return export_crosswalk_csv(result["candidates"])
