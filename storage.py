# in-memory list storage per user session
from collections import defaultdict

_sessions = defaultdict(list)

def append(user_id: int, entry: dict):
    _sessions[user_id].append(entry)

def dump(user_id: int) -> list:
    return _sessions.get(user_id, [])

def clear(user_id: int):
    _sessions[user_id] = []
