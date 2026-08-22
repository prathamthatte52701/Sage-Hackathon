import yaml
def load_settings(raw_text: str):
    return yaml.load(raw_text, Loader=yaml.Loader)
