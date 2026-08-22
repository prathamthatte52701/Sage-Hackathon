import time,requests
def fetch_until_success(url: str):
    while True:
        try:
            r=requests.get(url,timeout=3); r.raise_for_status(); return r.json()
        except requests.RequestException:
            time.sleep(1)
