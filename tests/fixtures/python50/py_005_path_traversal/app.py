from pathlib import Path
UPLOAD_ROOT = Path('/srv/app/uploads')
def read_upload(filename: str):
    return (UPLOAD_ROOT / filename).read_text(encoding='utf-8')
