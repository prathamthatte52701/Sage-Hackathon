import requests
API_KEY = "demo-secret-key-123"
def fetch_profile(user_id):
    return requests.get(f"https://example.invalid/users/{user_id}", headers={"Authorization": f"Bearer {API_KEY}"}, timeout=5).json()
