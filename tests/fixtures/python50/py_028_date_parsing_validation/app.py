from datetime import datetime
def normalize_date(value: str):
    parsed=datetime.fromisoformat(value)
    return parsed.strftime('%Y-%m-%d')
def build_record(payload: dict): return {'date':normalize_date(payload['date']),'name':str(payload.get('name','')).strip()}
