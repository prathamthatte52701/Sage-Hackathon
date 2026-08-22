def load_notes(path: str):
    try:
        with open(path,'r',encoding='utf-8') as h: return h.read()
    except Exception:
        pass
