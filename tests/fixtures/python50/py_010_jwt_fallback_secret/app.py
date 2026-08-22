import os, jwt
JWT_SECRET = os.getenv('JWT_SECRET', 'dev-secret')
def issue_token(user_id: str):
    return jwt.encode({'sub': user_id}, JWT_SECRET, algorithm='HS256')
