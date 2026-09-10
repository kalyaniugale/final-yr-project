"""Deterministic transitions. Sender identity never becomes a registry vendor ID."""
import hashlib
import uuid
from . import messages as m
from .translations import LANGUAGES, CATEGORIES, localized, t
from .recommendation_client import BackendError


def new_session():
    return {"language": "en", "state": "LANGUAGE", "vendor_type": "", "business": "",
            "division": "", "recommendations": [], "selected_zone_id": "", "snapshot": ""}


class Conversation:
    def __init__(self, backend):
        self.backend = backend

    def language(self):
        return [m.buttons("Welcome! / स्वागत! Choose language / भाषा निवडा / भाषा चुनें", [
            ("lang:en", "English"), ("lang:mr", "मराठी"), ("lang:hi", "हिन्दी")])]

    def main(self, s):
        return [m.buttons(t(s["language"], "menu"), [("find", t(s["language"], "find")), ("help", t(s["language"], "help"))])]

    def navigation(self, s):
        lang = s["language"]
        choices = [("restart", t(lang, "restart"))]
        if s["recommendations"]:
            choices.insert(0, ("results", t(lang, "back")))
        return [m.buttons(t(lang, "navigation"), choices)]

    def actions(self, s):
        lang = s["language"]
        return [m.buttons(t(lang, "actions"), [(f"view:{s['snapshot']}:{s['selected_zone_id']}:{key}", t(lang, key))
                                               for key in ("simple", "detailed", "map")])] + self.navigation(s)

    async def business_menu(self, s):
        options = await self.backend.options()
        # Translations define presentation only; the API determines supported codes.
        codes = [code for code in options["categories"] if code in CATEGORIES]
        if not codes:
            raise BackendError()
        s["categories"] = codes
        s["state"] = "BUSINESS"
        lang = s["language"]
        return [m.list_message(lang, t(lang, "business"), [("business:" + code,
                localized(CATEGORIES[code][0], lang), localized(CATEGORIES[code][1], lang)) for code in codes])]

    async def division_menu(self, s, page=0):
        options = await self.backend.options()
        if s["business"] not in options["categories"]:
            raise BackendError("invalid")
        # Hash the exact backend name: IDs remain stable when translated or reordered.
        mapping = {"division:any": ""}
        mapping.update({"division:" + hashlib.sha256(name.encode()).hexdigest()[:16]: name for name in options["divisions"]})
        s["divisions"] = mapping
        s["state"] = "DIVISION"
        lang = s["language"]
        rows = [(key, name or t(lang, "any"), "") for key, name in mapping.items()]
        start = page * 9
        if start >= len(rows) or page < 0:
            start, page = 0, 0
        visible = rows[start:start+9]
        if start + 9 < len(rows):
            visible.append((f"page:{page+1}", t(lang, "next"), ""))
        return [m.list_message(lang, t(lang, "division"), visible)]

    async def handle(self, session, value):
        s = session or new_session()
        lang = s["language"]
        command = value.strip().lower()
        if command in ("hi", "hello", "start", "restart", "menu", "language", "नमस्ते", "नमस्कार") or session is None:
            s = new_session()
            return s, self.language()
        try:
            if s["state"] == "LANGUAGE" and value.startswith("lang:") and value[5:] in LANGUAGES:
                s["language"], s["state"] = value[5:], "MAIN_MENU"
                return s, self.main(s)
            if value == "results" and s["recommendations"]:
                s["state"] = "RESULTS"
                return s, m.result_messages(lang, s["recommendations"], s["snapshot"]) + self.navigation(s)
            if s["state"] == "MAIN_MENU":
                if value == "help":
                    return s, m.texts(t(lang, "help_text")) + self.main(s)
                if value == "find":
                    s["state"] = "VENDOR_TYPE"
                    return s, [m.buttons(t(lang, "vendor"), [("vendor:new", t(lang, "new")), ("vendor:existing", t(lang, "existing"))])]
            if s["state"] == "VENDOR_TYPE" and value in ("vendor:new", "vendor:existing"):
                s["vendor_type"] = value.split(":")[1]
                prefix = m.texts(t(lang, "manual")) if s["vendor_type"] == "existing" else []
                return s, prefix + await self.business_menu(s)
            if s["state"] == "BUSINESS" and value.startswith("business:") and value[9:] in s.get("categories", []):
                s["business"] = value[9:]
                return s, await self.division_menu(s)
            if s["state"] == "DIVISION":
                if value.startswith("page:") and value[5:].isdigit():
                    return s, await self.division_menu(s, int(value[5:]))
                if value in s.get("divisions", {}):
                    s["division"] = s["divisions"][value]
                    s["state"] = "RECOMMENDING"
                    rows = await self.backend.recommend(s["business"], s["division"])
                    s["recommendations"], s["snapshot"] = rows, uuid.uuid4().hex[:12]
                    s["selected_zone_id"], s["state"] = "", "RESULTS"
                    return s, (m.result_messages(lang, rows, s["snapshot"]) if rows else m.texts(t(lang, "empty"))) + self.navigation(s)
            prefix = f"zone:{s['snapshot']}:"
            if s["state"] == "RESULTS" and value.startswith(prefix):
                index = value[len(prefix):]
                if index.isdigit() and int(index) < len(s["recommendations"]):
                    r = s["recommendations"][int(index)]
                    s["selected_zone_id"], s["state"] = r["zone_id"], "SELECTED_ZONE"
                    return s, m.texts(r["official_description"]) + self.actions(s)
            prefix = f"view:{s['snapshot']}:{s['selected_zone_id']}:"
            if s["state"] in ("SELECTED_ZONE", "SIMPLE_EXPLANATION", "DETAILED_ANALYSIS", "MAP") and value.startswith(prefix):
                action = value[len(prefix):]
                r = next(r for r in s["recommendations"] if r["zone_id"] == s["selected_zone_id"])
                if action == "simple":
                    s["state"] = "SIMPLE_EXPLANATION"
                    return s, m.simple(lang, r) + self.actions(s)
                if action == "detailed":
                    s["state"] = "DETAILED_ANALYSIS"
                    return s, m.detailed(lang, r) + self.actions(s)
                if action == "map":
                    s["state"] = "MAP"
                    point = await self.backend.point(r["zone_id"])
                    out = m.texts(t(lang, "map_caveat") + "\n" + m.warning(lang, r))
                    out += [m.location(lang, r, point)] if point else m.texts(t(lang, "no_map"))
                    return s, out + self.actions(s)
            return s, m.texts(t(lang, "invalid_choice")) + self.navigation(s)
        except BackendError as exc:
            # Retry by selecting the same division, or restart with fresh options.
            if s["state"] == "RECOMMENDING":
                s["state"] = "DIVISION"
            return s, m.texts(t(lang, exc.kind)) + self.navigation(s)
