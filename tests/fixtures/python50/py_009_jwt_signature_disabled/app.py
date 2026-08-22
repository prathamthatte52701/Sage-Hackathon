import jwt
def decode_access_token(token: str):
    return jwt.decode(token, options={"verify_signature": False})
