import os
from pathlib import Path
def save_config(text: str):
    path=Path('/tmp/app-config.json'); path.write_text(text,encoding='utf-8'); os.chmod(path,0o777); return str(path)
