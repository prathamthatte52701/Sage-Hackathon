import requests
def preview(url: str):
    r = requests.get(url, timeout=4)
    return {"status": r.status_code, "body": r.text[:500]}
