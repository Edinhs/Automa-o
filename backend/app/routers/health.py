from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
def health_check():
    return {"status": "ok"}

@router.get("/api/health")
def api_health_check():
    return {"status": "ok"}
