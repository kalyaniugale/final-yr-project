"""WhatsApp payload builders and evidence-only presentation."""
from .translations import t, localized, FACTOR_LABELS, FACTOR_DETAILS
from .recommendation_client import number


def texts(body):
    # Conservative chunk size leaves space below the 4096-character text limit.
    return [{"type": "text", "text": {"body": body[i:i+3500], "preview_url": False}}
            for i in range(0, len(body), 3500)]


def buttons(body, choices):
    if not 1 <= len(choices) <= 3 or len(body) > 1024:
        raise ValueError("Invalid reply menu")
    return {"type": "interactive", "interactive": {"type": "button", "body": {"text": body},
        "action": {"buttons": [{"type": "reply", "reply": {"id": key, "title": label[:20]}}
                               for key, label in choices]}}}


def list_message(lang, body, rows):
    if not 1 <= len(rows) <= 10:
        raise ValueError("List requires 1–10 rows")
    return {"type": "interactive", "interactive": {"type": "list", "body": {"text": body[:1024]},
        "action": {"button": t(lang, "choose")[:20], "sections": [{"rows": [
            {"id": key, "title": label[:24], "description": desc[:72]}
            for key, label, desc in rows]}]}}}


def fmt(value, lang, digits=0):
    return f"{value:.{digits}f}" if number(value) else t(lang, "unknown")


def fact(lang, key, r):
    n = lambda key: fmt(r.get(key), lang)
    if key == "business":
        return t(lang, "business_fact", same=n("same_business_count"), total=n("evidence_count"))
    if key == "commercial":
        return t(lang, "commercial_fact", markets=n("market_poi_count_500m"), shops=n("commercial_poi_count_250m"))
    if key == "access":
        return t(lang, "access_fact", road=n("distance_to_major_road_m"), bus=n("distance_to_bus_access_m"))
    if key == "facilities":
        return t(lang, "facilities_fact", health=n("healthcare_count_500m"), education=n("education_count_500m"),
                 toilets=n("toilet_count_500m"), parking=n("parking_count_500m"))
    if key == "preference":
        return t(lang, "preference_fact", division=r["zone_division"]) + (
            " " + t(lang, "fallback") if r.get("fallback_used") else "")
    return t(lang, "historical_fact", total=n("evidence_count"))


def warning(lang, r):
    result = t(lang, "caveat")
    if r.get("shared_reference"):
        result += "\n" + t(lang, "shared", count=fmt(r.get("shared_reference_group_size"), lang))
    return result


def result_messages(lang, rows, snapshot):
    out = texts(t(lang, "results", count=len(rows)))
    for r in rows:
        factors = [f for f in r["factors"] if f["key"] not in ("preference", "historical") and number(f.get("score"))]
        strongest = max(factors, key=lambda f: f["score"], default=None)
        reason = (strongest["summary"] if lang == "en" else fact(lang, strongest["key"], r)) if strongest else t(lang, "unknown")
        body = (f"{r['rank']}. {r['official_description']}\n{r['zone_id']} · {r['zone_division']}\n"
                f"{t(lang, 'index')}: {fmt(r.get('score'), lang, 1)}/100\n{reason}")
        if r.get("fallback_used"):
            body += "\n" + t(lang, "fallback")
        out.extend(texts(body))
    out.extend(texts(t(lang, "caveat")))
    out.append(buttons(t(lang, "select"), [(f"zone:{snapshot}:{i}", t(lang, "zone", rank=r["rank"]))
                                          for i, r in enumerate(rows)]))
    return out


def simple(lang, r):
    return texts(r["official_description"] + "\n\n" + "\n".join(
        fact(lang, f["key"], r) for f in r["factors"]) + "\n\n" + warning(lang, r))


def detailed(lang, r):
    out = texts(f"{r['zone_id']} · {t(lang, 'index')}: {fmt(r.get('score'), lang, 1)}/100\n" +
                t(lang, "coverage", coverage=fmt(r.get("score_coverage"), lang, 3)))
    for f in r["factors"]:
        score = f.get("score")
        body = localized(FACTOR_LABELS[f["key"]], lang) + "\n" + t(lang, "metrics",
            score=fmt(score * 100 if number(score) else None, lang, 1),
            weight=fmt(f.get("weight"), lang, 1), contribution=fmt(f.get("contribution"), lang, 2))
        if lang == "en":
            body += "\n" + f["summary"] + "\n" + f["details"]
            body += "\n" + "\n".join(f"{e.get('label', '')}: {e.get('value') if e.get('value') is not None else t(lang, 'unknown')}"
                                     for e in f["evidence"])
        else:
            body += "\n" + fact(lang, f["key"], r) + "\n" + localized(FACTOR_DETAILS[f["key"]], lang)
        out.extend(texts(body))
    out.extend(texts(warning(lang, r)))
    return out


def location(lang, r, point):
    lat, lon = point
    return {"type": "location", "location": {"latitude": lat, "longitude": lon,
        "name": t(lang, "map_name"),
        "address": f"{r['zone_id']} · {r['official_description']} · {r['zone_division']}"[:500]}}
