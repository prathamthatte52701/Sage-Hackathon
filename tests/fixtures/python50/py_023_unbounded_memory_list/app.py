import time
recent_events=[]
def record_event(name: str): recent_events.append({'name':name,'ts':time.time()})
def recent_count(): return len(recent_events)
