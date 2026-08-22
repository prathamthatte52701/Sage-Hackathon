import asyncio
counter=0
async def record_event():
    global counter
    current=counter
    await asyncio.sleep(0)
    counter=current+1
    return counter
