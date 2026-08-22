import asyncio
results={}
async def expensive_generate(key: str, provider):
    if key in results: return results[key]
    value=await provider.generate(key)
    results[key]=value
    return value
async def run_twice(provider):
    return await asyncio.gather(expensive_generate('monthly',provider), expensive_generate('monthly',provider))
