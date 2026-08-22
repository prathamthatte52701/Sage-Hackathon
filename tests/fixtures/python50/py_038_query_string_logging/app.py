import logging
from fastapi import FastAPI,Request
app=FastAPI(); logger=logging.getLogger(__name__)
@app.middleware('http')
async def log_request(request: Request, call_next):
    logger.info('request_url=%s',str(request.url))
    return await call_next(request)
