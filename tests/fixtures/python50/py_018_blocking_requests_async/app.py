import requests
from fastapi import FastAPI
app=FastAPI()
@app.get('/preview')
async def preview(url: str):
    r=requests.get(url, timeout=5)
    return {'status': r.status_code}
