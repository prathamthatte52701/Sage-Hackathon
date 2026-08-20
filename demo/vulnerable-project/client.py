import requests


def fetch_report(url):
    return requests.get(url, verify=False)
