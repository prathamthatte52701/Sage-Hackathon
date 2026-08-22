def list_events(db,page: int):
    page_size=100; offset=page*page_size
    return db.execute('SELECT id,created_at,message FROM events ORDER BY created_at DESC LIMIT ? OFFSET ?', (page_size,offset)).fetchall()
