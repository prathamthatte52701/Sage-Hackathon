from fastapi import FastAPI
app=FastAPI(); ORDERS={'o1':{'owner_id':'u1','total':45},'o2':{'owner_id':'u2','total':80}}
@app.get('/users/{user_id}/orders/{order_id}')
async def get_order(user_id: str, order_id: str):
    order=ORDERS.get(order_id)
    if not order: return {'error':'not found'}
    return {'requested_user': user_id, 'order': order}
