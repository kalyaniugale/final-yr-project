"""HTTP boundary only: no ranking, eligibility or historical calculations."""
import math
import httpx


class BackendError(Exception):
    def __init__(self, kind="unexpected"):
        self.kind = kind
        super().__init__(kind)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class RecommendationClient:
    def __init__(self, http, base_url):
        self.http, self.base_url = http, base_url.rstrip("/")

    async def request(self, method, path, **kwargs):
        try:
            r = await self.http.request(method, self.base_url + path, **kwargs)
            if r.status_code == 422:
                raise BackendError("invalid")
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise BackendError()
            return data
        except httpx.TimeoutException:
            raise BackendError("timeout") from None
        except httpx.HTTPError:
            raise BackendError("unavailable") from None
        except (ValueError, TypeError):
            raise BackendError() from None

    async def options(self):
        data = await self.request("GET", "/api/options")
        for key in ("categories", "divisions"):
            values = data.get(key)
            if not isinstance(values, list) or not values or any(not isinstance(x, str) or not x for x in values):
                raise BackendError()
            if len(set(values)) != len(values):
                raise BackendError()
        return data

    async def recommend(self, business, division):
        data = await self.request("POST", "/api/recommendations", json={
            "business": business, "division": division, "vendor_id": "",
            "exclude_zone": "", "top_n": 3, "require_verified": False})
        rows = data.get("recommendations")
        if not isinstance(rows, list) or len(rows) > 3 or data.get("count") != len(rows):
            raise BackendError()
        ids = set()
        for r in rows:
            if not isinstance(r, dict) or any(not isinstance(r.get(k), str) or not r[k]
                    for k in ("zone_id", "official_description", "zone_division")):
                raise BackendError()
            if r["zone_id"] in ids or type(r.get("rank")) is not int or not 1 <= r["rank"] <= 3:
                raise BackendError()
            ids.add(r["zone_id"])
            if "score" not in r or (r["score"] is not None and (not number(r["score"]) or not 0 <= r["score"] <= 100)):
                raise BackendError()
            if not number(r.get("score_coverage")) or not 0 < r["score_coverage"] <= 1.000000001:
                raise BackendError()
            factors = r.get("factors")
            if not isinstance(factors, list) or len(factors) != 6:
                raise BackendError()
            if any(not isinstance(f, dict) or not isinstance(f.get("key"), str) for f in factors):
                raise BackendError()
            if {f["key"] for f in factors} != {
                    "business", "commercial", "access", "facilities", "preference", "historical"}:
                raise BackendError()
            for f in factors:
                if any(not isinstance(f.get(k), str) for k in ("label", "summary", "details")):
                    raise BackendError()
                if any(f.get(k) is not None and not number(f[k]) for k in ("score", "weight", "contribution")):
                    raise BackendError()
                if not number(f.get("weight")) or not 0 <= f["weight"] <= 100:
                    raise BackendError()
                if f.get("score") is not None and not 0 <= f["score"] <= 1:
                    raise BackendError()
                if not isinstance(f.get("evidence"), list) or any(not isinstance(e, dict) for e in f["evidence"]):
                    raise BackendError()
        return rows

    async def point(self, zone_id):
        data = await self.request("GET", "/api/zones/geometry")
        if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
            raise BackendError()
        for f in data["features"]:
            if not isinstance(f, dict) or not isinstance(f.get("properties"), dict):
                continue
            if f["properties"].get("zone_id") != zone_id:
                continue
            g = f.get("geometry") or {}
            if not isinstance(g, dict):
                continue
            c = g.get("coordinates")
            if g.get("type") == "Point" and isinstance(c, list) and len(c) >= 2:
                lon, lat = c[:2]
                if number(lon) and number(lat) and -180 <= lon <= 180 and -90 <= lat <= 90:
                    return lat, lon
        return None
