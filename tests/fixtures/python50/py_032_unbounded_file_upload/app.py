from fastapi import FastAPI, UploadFile
app=FastAPI()
@app.post('/upload')
async def upload(file: UploadFile):
    content=await file.read()
    with open(f'/tmp/{file.filename}','wb') as h: h.write(content)
    return {'bytes':len(content)}
