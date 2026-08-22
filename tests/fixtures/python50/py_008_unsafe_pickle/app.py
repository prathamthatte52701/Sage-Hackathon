import pickle
def restore_session(blob: bytes):
    return pickle.loads(blob)
