from fastapi import FastAPI
app=FastAPI()
@app.get('/account/{account_id}')
async def account(account_id: int):
    try:
        if account_id < 0: raise ValueError('internal lookup failed on shard alpha')
        return {'id': account_id}
    except Exception as exc:
        return {'ok': False, 'error': repr(exc)}
