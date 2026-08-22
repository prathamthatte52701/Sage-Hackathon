import re
def search_notes(notes: list[str], pattern: str):
    regex=re.compile(pattern,re.IGNORECASE)
    return [note for note in notes if regex.search(note)]
