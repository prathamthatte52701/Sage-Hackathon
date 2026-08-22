from fastapi import FastAPI
app=FastAPI(); ROWS=[{'id':i,'name':f'item-{i}'} for i in range(50000)]
@app.get('/items')
async def list_items():
    return {'items': ROWS}
