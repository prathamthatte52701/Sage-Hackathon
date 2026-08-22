summary_cache={}
def get_summary(user_id: str, database):
    if user_id in summary_cache: return summary_cache[user_id]
    value=database.calculate_summary(user_id); summary_cache[user_id]=value; return value
def add_transaction(user_id: str, transaction, database):
    database.insert_transaction(user_id, transaction)
    return {'saved':True}
