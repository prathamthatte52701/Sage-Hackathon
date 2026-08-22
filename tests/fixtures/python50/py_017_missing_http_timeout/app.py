import requests
def exchange_rate(base: str, quote: str):
    r=requests.get(f'https://example.invalid/rates/{base}/{quote}')
    r.raise_for_status(); return r.json()
