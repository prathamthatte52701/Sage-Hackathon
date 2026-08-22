import requests
def download_manifest(url: str):
    r=requests.get(url,timeout=5,verify=False)
    r.raise_for_status(); return r.text
