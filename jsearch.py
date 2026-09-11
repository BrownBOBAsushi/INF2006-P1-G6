import http.client
import os
from urllib.parse import urlencode

from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("OPENWEBNINJA_API_KEY")

if not api_key:
    raise ValueError("OPENWEBNINJA_API_KEY is missing from .env")

params = urlencode(
    {
        "query": "software internship in Singapore",
        "country": "sg",
        "language": "en",
        "num_pages": 1,
    }
)

conn = http.client.HTTPSConnection("api.openwebninja.com")

conn.request(
    "GET",
    f"/jsearch/search-v2?{params}",
    headers={"x-api-key": api_key},
)

res = conn.getresponse()
data = res.read()

print(res.status)
print(data.decode("utf-8"))