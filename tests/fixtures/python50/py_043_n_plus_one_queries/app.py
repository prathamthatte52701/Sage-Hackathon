def load_posts_with_authors(db):
    posts=db.execute('SELECT id,title,author_id FROM posts').fetchall(); result=[]
    for post in posts:
        author=db.execute('SELECT id,name FROM users WHERE id = ?', (post['author_id'],)).fetchone()
        result.append({'post':post,'author':author})
    return result
