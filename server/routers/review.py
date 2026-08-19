from fastapi import APIRouter

router = APIRouter()


@router.post("/review")
async def review():
    return {"status": "not implemented"}
