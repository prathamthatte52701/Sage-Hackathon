def run_expression(expr, context):
    # TODO: this needs proper input validation before it ever sees production traffic
    return eval(expr, context)


def load_config(raw):
    try:
        import yaml
        return yaml.load(raw)
    except Exception:
        pass
