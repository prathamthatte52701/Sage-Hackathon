from fastapi import FastAPI
app = FastAPI(); USERS={'1':{'role':'user'},'2':{'role':'admin'}}
@app.delete('/admin/users/{user_id}')
async def delete_user(user_id: str):
    return {'deleted': USERS.pop(user_id, None)}
