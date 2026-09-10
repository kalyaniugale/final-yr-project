"""Cloud API transport. Do not log bodies, recipient IDs, URLs or credentials."""
import logging
import httpx

log = logging.getLogger(__name__)


class MetaError(Exception):
    def __init__(self, retryable):
        self.retryable = retryable


class MetaClient:
    def __init__(self, http, settings):
        self.http = http
        self.url = f"https://graph.facebook.com/{settings.graph_version}/{settings.phone_number_id}/messages"
        self.token = settings.access_token

    async def send(self, sender, payload):
        try:
            r = await self.http.post(self.url,
                headers={"Authorization": "Bearer " + self.token},
                json={"messaging_product": "whatsapp", "recipient_type": "individual",
                      "to": sender, **payload})
            if r.is_error:
                log.warning("Meta send failed: HTTP %s", r.status_code)
                raise MetaError(r.status_code == 429 or r.status_code >= 500)
        except httpx.HTTPError:
            log.warning("Meta transport failure")
            raise MetaError(True) from None
