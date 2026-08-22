def calculate(expression: str):
    return eval(expression)
def handler(payload: dict):
    return {"result": calculate(str(payload.get("expression", "0")))}
