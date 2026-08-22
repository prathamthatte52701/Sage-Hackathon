def checkout_total(prices: list[float], tax_rate: float) -> float:
    subtotal=sum(prices); tax=subtotal*tax_rate; return subtotal+tax
def split_bill(total: float, people: int) -> float: return total/people
