import asyncio
async def send_email(address: str): raise RuntimeError('mail provider unavailable')
async def register_user(address: str):
    asyncio.create_task(send_email(address))
    return {'created':True}
