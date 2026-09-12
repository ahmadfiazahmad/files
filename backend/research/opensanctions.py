"""Global sanctions/watchlist screening via OpenSanctions."""
import logging

import httpx
from config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.opensanctions.org"
TIMEOUT = 15.0


async def screen_entity(name: str, country: str | None = None) -> dict:
    if not settings.opensanctions_api_key:
        return {"error": "OPENSANCTIONS_API_KEY is not configured", "query": name, "results": []}

    properties = {"name": [name]}
    if country:
        properties["country"] = [country]
    query = {"schema": "Company", "properties": properties}
    headers = {"Authorization": f"ApiKey {settings.opensanctions_api_key}", "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(
                f"{BASE_URL}/match/default",
                params={"algorithm": "best", "threshold": 0.7, "limit": 5},
                json={"queries": {"agent": query}},
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            results = data.get("responses", {}).get("agent", {}).get("results", [])
            return {
                "query": name,
                "total_matches": len(results),
                "results": [
                    {"id": r.get("id"), "name": r.get("caption"), "score": r.get("score"),
                     "schema": r.get("schema"), "datasets": r.get("datasets"), "properties": r.get("properties", {})}
                    for r in results
                ],
            }
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("OpenSanctions screening failed for %r: %s", name, exc)
        return {"error": str(exc), "query": name, "results": []}
