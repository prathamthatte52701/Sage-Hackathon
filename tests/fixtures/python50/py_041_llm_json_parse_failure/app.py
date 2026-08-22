import json
async def generate(provider,prompt: str):
    raw=await provider.complete(prompt)
    data=json.loads(raw)
    return {'title':data['title'],'summary':data['summary']}
