from flask import Flask,request,session
app=Flask(__name__); app.secret_key='test-session-secret'
@app.post('/profile/email')
def update_email():
    if 'user_id' not in session: return {'error':'login required'},401
    new_email=request.form['email']
    return {'updated_user':session['user_id'],'email':new_email}
