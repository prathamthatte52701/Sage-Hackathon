from pathlib import Path
from zipfile import ZipFile
EXTRACT_ROOT=Path('/srv/app/extracted')
def unpack(upload_path: str):
    with ZipFile(upload_path) as archive: archive.extractall(EXTRACT_ROOT)
    return {'ok':True}
