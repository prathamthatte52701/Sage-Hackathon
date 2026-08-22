def transfer_balance(db,from_id: str,to_id: str,amount: int):
    db.execute('UPDATE accounts SET balance = balance - ? WHERE id = ?', (amount,from_id))
    db.execute('UPDATE accounts SET balance = balance + ? WHERE id = ?', (amount,to_id))
    db.commit(); return {'transferred':amount}
