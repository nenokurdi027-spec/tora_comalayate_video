# ip geolocation — uses ipinfo.io free API (no key needed for basic tier)
import aiohttp
from config import IPINFO_TOKEN

async def lookup_ip(ip: str) -> dict:
    url = f"https://ipinfo.io/{ip}/json"
    headers = {}
    if IPINFO_TOKEN:
        url += f"?token={IPINFO_TOKEN}"
    async with aiohttp.ClientSession() as s:
        async with s.get(url, headers=headers, timeout=10) as r:
            if r.status != 200:
                return {"error": f"http {r.status}"}
            data = await r.json()
    loc = data.get("loc", "")  # "lat,lon"
    maps = f"https://www.google.com/maps?q={loc}" if loc else None
    return {
        "ip": ip,
        "city": data.get("city"),
        "region": data.get("region"),
        "country": data.get("country"),
        "org": data.get("org"),
        "loc": loc,
        "maps_link": maps,
    }
