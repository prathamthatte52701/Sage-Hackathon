from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from models.schemas import ExplainRequest
from services.auth import get_request_user
from services.groq_client import GroqUnavailableError, call_groq
from services.prompt_builder import build_explain_prompt

router = APIRouter()

_ERROR_RESPONSE = {"error": "Could not generate explanation, please retry"}


@router.post("/explain-bug")
async def explain_bug(request: ExplainRequest, current_user: dict = Depends(get_request_user)):
    try:
        prompt = build_explain_prompt(request.issue, request.code_context, request.language)
        try:
            explanation = await call_groq([{"role": "user", "content": prompt}])
        except GroqUnavailableError:
            return JSONResponse(status_code=500, content=_ERROR_RESPONSE)
        return {"explanation": explanation}
    except Exception:
        return JSONResponse(status_code=500, content=_ERROR_RESPONSE)
