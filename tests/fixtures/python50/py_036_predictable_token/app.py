import random,string
def reset_token():
    alphabet=string.ascii_letters+string.digits
    return ''.join(random.choice(alphabet) for _ in range(32))
