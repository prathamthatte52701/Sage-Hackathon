from fastapi import FastAPI
from fastapi.responses import RedirectResponse
app=FastAPI()
@app.get('/continue')
async def continue_after_login(next_url: str):
    return RedirectResponse(next_url)
