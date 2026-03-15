from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import requests

from config import (
    CONFIG,
    MAX_RETRIES,
    INITIAL_BACKOFF_SEC,
    BACKOFF_FACTOR,
    JITTER_RANGE_SEC,
)

log = logging.getLogger(__name__)


@dataclass
class ParsedServiceInfo:
    services_active: List[str]
    commitment_end_date: Optional[datetime]
    price_cards: List[str]


@dataclass
class ScrapeResult:
    status_code: int
    raw_text: str
    parsed: Optional[ParsedServiceInfo]


class TelekomClient:
    def fetch(self, service_id: str, attempt: int = 1) -> ScrapeResult:
        try:
            # --- Payload to send ---
            payload = {
                "serviceId": service_id,  # or try "msisdn" if 400 persists
                "source": CONFIG.API_SOURCE,
                "mode": CONFIG.API_MODE,
                "scenario": CONFIG.API_SCENARIO,
            }

            # --- DEBUG PRINTS ---
            print("URL:", CONFIG.API_URL)
            print("Payload:", payload)

            # --- Send POST request ---
            resp = requests.post(
                CONFIG.API_URL,
                json=payload,
                timeout=CONFIG.API_TIMEOUT_SEC,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json",
                    "User-Agent": "telekom-scraper/1.0",
                },
            )

            # --- Debug response ---
            print("Response status:", resp.status_code)
            
            if resp.text:
            # Print only the first part of the response up to and including commitmentEnd line
                lines = resp.text.splitlines()
                out_lines = []
                for line in lines:
                    out_lines.append(line)
                    if '"commitmentEnd"' in line or '"commitment_end"' in line:
                        break
                print("Response text :", "\n".join(out_lines))
           
            status = resp.status_code
            text = resp.text
            parsed = None

            # Try to parse JSON only if successful
            if status == 200:
                parsed = self._parse_response(resp)
            elif status == 204:
                log.info("No content for %s", service_id)
                return ScrapeResult(status_code=204, raw_text="", parsed=None)

            return ScrapeResult(status_code=status, raw_text=text, parsed=parsed)

        except requests.RequestException as e:
            log.warning(
                "request_failed",
                extra={
                    "extra_service_id": service_id,
                    "extra_attempt": attempt,
                    "extra_error": str(e),
                },
            )
            if attempt >= MAX_RETRIES:
                raise
            self._sleep_backoff(attempt)
            return self.fetch(service_id, attempt + 1)

            

    # --- Domain parsing ---
    def _parse_response(self, resp: requests.Response) -> Optional[ParsedServiceInfo]:
        try:
            data = resp.json()
        except ValueError:
            log.info("non_json_response")
            return None

        services_active: List[str] = []
        commitment_end_dt: Optional[datetime] = None
        price_cards: List[str] = []

        services = data.get("services") or []
        for s in services:
            if (s or {}).get("promo") == "active":
                name = (s or {}).get("rtplName")
                if isinstance(name, str):
                    services_active.append(name)

        commitment = data.get("commitmentEnd") or data.get("commitment")
        if isinstance(commitment, str):
            commitment_end_dt = _parse_datetime(commitment)

        for s in services:
            if (s or {}).get("promo") == "proposed":
                desc = (s or {}).get("description") or (s or {}).get("rtplName")
                if isinstance(desc, str):
                    price_cards.append(desc)

        return ParsedServiceInfo(
            services_active=services_active,
            commitment_end_date=commitment_end_dt,
            price_cards=price_cards,
        )

    def _sleep_backoff(self, attempt: int) -> None:
        base = INITIAL_BACKOFF_SEC * (BACKOFF_FACTOR ** max(0, attempt - 1))
        delay = base + random.uniform(0, JITTER_RANGE_SEC)
        log.debug("backoff_sleep", extra={"extra_attempt": attempt, "extra_delay": delay})
        time.sleep(delay)


def _parse_datetime(value: str) -> Optional[datetime]:
    """Try multiple formats safely."""
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
