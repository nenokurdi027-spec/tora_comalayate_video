import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
IPINFO_TOKEN = os.getenv("IPINFO_TOKEN", "")  # optional, ipinfo.io free tier

# how many of the target's groups to enumerate per lookup
MAX_GROUPS = 200
