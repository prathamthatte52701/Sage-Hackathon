class User:
    def __init__(self):
        self.display_name=''; self.role='user'; self.is_admin=False
def update_user(user: User,payload: dict):
    for key,value in payload.items(): setattr(user,key,value)
    return user
