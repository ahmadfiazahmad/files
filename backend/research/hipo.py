"""Free/keyless university-identity lookup via the Hipo Universities API."""
import logging

import httpx

logger = logging.getLogger(__name__)

HIPO_URL = "http://universities.hipolabs.com/search"
TIMEOUT = 10.0


async def search_university(name: str, country: str | None = None) -> dict:
    params = {"name": name}
    if country:
        params["country"] = country
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.get(HIPO_URL, params=params)
            response.raise_for_status()
            return {"query": name, "country": country, "matches": response.json()}
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Hipo university lookup failed for %r: %s", name, exc)
        return {"error": str(exc), "query": name, "country": country, "matches": []}
