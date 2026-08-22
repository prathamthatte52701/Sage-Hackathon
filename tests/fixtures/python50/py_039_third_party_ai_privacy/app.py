import requests
def summarize_finances(user):
    payload={'name':user['name'],'email':user['email'],'transactions':user['transactions'],'account_number':user['account_number']}
    r=requests.post('https://example-ai.invalid/v1/analyze',json=payload,timeout=10)
    return r.json()
