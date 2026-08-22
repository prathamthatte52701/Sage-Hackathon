import time
from fastapi import FastAPI
app=FastAPI()
@app.post('/reports')
async def create_report():
    time.sleep(3)
    return {'status':'ready'}
