from fastapi import FastAPI
app=FastAPI(); profile_cache={}
@app.get('/users/{user_id}')
async def get_user(user_id: str):
    if user_id not in profile_cache: profile_cache[user_id]={'id':user_id,'name':'User'}
    return profile_cache[user_id]
