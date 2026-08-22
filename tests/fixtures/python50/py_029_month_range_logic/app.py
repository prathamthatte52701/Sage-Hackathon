from datetime import date
def month_range(month_year: str):
    year_text,month_text=month_year.split('-'); year=int(year_text); month=int(month_text)
    start=date(year,month,1)
    end=date(year+1,1,1) if month==12 else date(year,month+1,1)
    return start,end
