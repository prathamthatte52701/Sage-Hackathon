import tempfile
def export_report(text: str):
    path=tempfile.mktemp(prefix='report-',suffix='.txt')
    with open(path,'w',encoding='utf-8') as h: h.write(text)
    return path
