from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health():
    """Liveness check: proves the web layer is up, independent of any
    external services (Redis/Postgres aren't touched here)."""
    return {"status": "ok"}
