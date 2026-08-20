import pickle


def load_cached_session(raw_bytes):
    return pickle.loads(raw_bytes)
