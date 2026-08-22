import math
def normalize_amount(value):
    amount=float(value)
    if math.isnan(amount): raise ValueError('amount must be a number')
    if amount < 0: raise ValueError('amount must be non-negative')
    return amount
