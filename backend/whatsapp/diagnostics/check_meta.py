"""Read-only checks by default. --send sends ONE text to WHATSAPP_TEST_RECIPIENT.

Run from the repository root with .venv/bin/python -B -m
backend.whatsapp.diagnostics.check_meta. Does not change subscriptions or bot config.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
from urllib.parse import urlsplit, urlunsplit
import httpx

WABA = "3016542835352548"
PHONE = "1302749026256977"


def read_env(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        key, sep, raw = line.partition("=")
        if sep:
            parts = shlex.split(raw, comments=True)
            values[key.strip()] = " ".join(parts)
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default="backend/whatsapp/.env")
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    disk = read_env(args.env_file)
    env = {**disk, **os.environ}
    secret_keys = [k for k in env if any(word in k.upper() for word in ("TOKEN", "SECRET", "PASSWORD", "RECIPIENT"))]
    secrets = [env[k] for k in secret_keys if env[k]]

    def scrub(value):
        if isinstance(value, dict):
            return {k: ("[REDACTED]" if (any(w in k.lower() for w in ("token", "secret")) and not isinstance(v, bool)) or k in ("input", "wa_id", "user_id") else scrub(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        if isinstance(value, str):
            if value.startswith("wamid."):
                return "[MESSAGE_ID_REDACTED]"
            for secret in secrets:
                value = value.replace(secret, "[REDACTED]")
            if value.startswith(("https://", "http://")):
                p = urlsplit(value)
                value = urlunsplit((p.scheme, p.netloc, p.path, "", ""))
        return value

    def report(label, data):
        print(label, json.dumps(scrub(data), ensure_ascii=False), flush=True)

    token = env.get("WHATSAPP_ACCESS_TOKEN", "")
    version = env.get("GRAPH_API_VERSION", "")
    report("CONFIG", {"phone_number_id": env.get("WHATSAPP_PHONE_NUMBER_ID"), "expected_test_phone": PHONE,
        "graph_version": version, "backend_url": env.get("RECOMMENDATION_BASE_URL"),
        "credential_presence": {k: bool(env.get(k)) for k in ("WHATSAPP_ACCESS_TOKEN", "META_APP_SECRET", "WHATSAPP_VERIFY_TOKEN")},
        "shell_differs_from_env_file": [k for k in disk if k in os.environ and disk[k] != os.environ[k]],
        "recipient_config_keys": [k for k in disk if "RECIPIENT" in k.upper()]})
    if not token or not version:
        return
    with httpx.Client(timeout=20, follow_redirects=False) as http:
        def graph(path, auth=token, params=None, body=None):
            try:
                r = http.request("POST" if body is not None else "GET", f"https://graph.facebook.com/{version}/{path}",
                                 headers={"Authorization": "Bearer " + auth}, params=params, json=body)
                try:
                    data = r.json()
                except ValueError:
                    data = {"non_json_body": r.text[:1000]}
                report(("POST " if body is not None else "GET ") + path, {"http_status": r.status_code, "body": data})
                return data if r.is_success else {}
            except httpx.HTTPError as exc:
                report(path, {"transport_error": type(exc).__name__})
                return {}

        for path in (WABA + "/subscribed_apps", PHONE + "?fields=id,display_phone_number,verified_name", WABA + "/phone_numbers"):
            graph(path)
        app = graph("app", params={"fields": "id,name"})
        app_id = app.get("id")
        if app_id and env.get("META_APP_SECRET"):
            app_auth = app_id + "|" + env["META_APP_SECRET"]
            secrets.append(app_auth)
            graph(app_id + "/subscriptions", auth=app_auth)
            graph("debug_token", auth=app_auth, params={"input_token": token})
        for url in ("http://127.0.0.1:8000/api/health", "http://127.0.0.1:8001/health", "http://127.0.0.1:4040/api/tunnels"):
            try:
                r = http.get(url)
                data = r.json()
                if "tunnels" in data:
                    data = [{"public_url": t.get("public_url"), "upstream": t.get("config", {}).get("addr")} for t in data["tunnels"]]
                report(url, {"http_status": r.status_code, "body": data})
            except (httpx.HTTPError, ValueError) as exc:
                report(url, {"error": type(exc).__name__})
        if args.send:
            recipient = env.get("WHATSAPP_TEST_RECIPIENT", "")
            if env.get("WHATSAPP_PHONE_NUMBER_ID") != PHONE or not recipient.isdigit():
                report("SEND_SKIPPED", "Requires matching test Phone Number ID and explicit WHATSAPP_TEST_RECIPIENT digits")
            else:
                graph(PHONE + "/messages", body={"messaging_product": "whatsapp", "to": recipient,
                    "type": "text", "text": {"body": "Review 2 diagnostic: testing delivery from the configured WhatsApp test number."}})
        else:
            report("SEND", "Not attempted (read-only run)")


if __name__ == "__main__":
    main()
