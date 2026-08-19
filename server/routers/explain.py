from fastapi import APIRouter

router = APIRouter()


@router.post("/explain-bug")
async def explain_bug():
    return {"status": "not implemented"}
