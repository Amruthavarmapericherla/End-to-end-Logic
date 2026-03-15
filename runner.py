from __future__ import annotations
import logging
from collections import deque
from datetime import datetime, timedelta

from config import CONFIG
from logging_setup import setup_logging
from mongo_repo import MongoRepo
from mysql_repo import MySQLRepo
from scraper import TelekomClient
from utils import sleep_with_jitter

log = logging.getLogger(__name__)


class Runner:
    def __init__(self, skip_existing: bool = False, limit: int | None = None, delay_sec: float | None = None):
        setup_logging(level=CONFIG.LOG_LEVEL, json_logs=CONFIG.LOG_JSON)
        self.mongo = MongoRepo()
        self.mysql = MySQLRepo()
        self.client = TelekomClient()
        self.skip_existing = skip_existing
        self.limit = min(int(limit or CONFIG.BATCH_LIMIT), CONFIG.BATCH_LIMIT)
        self.delay_sec = CONFIG.PROCESS_DELAY_SEC if delay_sec is None else float(delay_sec)
        self.mode = (CONFIG.SCRAPER_MODE or "COMMITMENT_WINDOW").upper()
        self.mix_window_limit = max(int(CONFIG.MIX_WINDOW_LIMIT_PER_CYCLE), 0)
        self.mix_annual_limit = max(int(CONFIG.MIX_ANNUAL_LIMIT_PER_CYCLE), 0)

    def run_once(self) -> int:
        setup_logging(level=CONFIG.LOG_LEVEL, json_logs=CONFIG.LOG_JSON)
        to_process = list(
            self.mongo.select_numbers_to_check(
                mode=self.mode,
                limit=self.limit,
                mix_window_limit=self.mix_window_limit,
                mix_annual_limit=self.mix_annual_limit,
            )
        )[: self.limit]
        mix_window_count = sum(1 for i in to_process if i.get("mode") == "COMMITMENT_WINDOW")
        mix_annual_count = sum(1 for i in to_process if i.get("mode") == "ANNUAL_REFRESH")
        log.info(
            "selection_done",
            extra={
                "extra_count": len(to_process),
                "extra_limit": self.limit,
                "extra_delay_sec": self.delay_sec,
                "extra_mode": self.mode,
                "extra_mix_window_count": mix_window_count if self.mode == "MIX" else None,
                "extra_mix_annual_count": mix_annual_count if self.mode == "MIX" else None,
                "extra_commitment_window_selected": mix_window_count if self.mode == "MIX" else None,
                "extra_annual_refresh_selected": mix_annual_count if self.mode == "MIX" else None,
                "extra_mix_window_limit": self.mix_window_limit if self.mode == "MIX" else None,
                "extra_mix_annual_limit": self.mix_annual_limit if self.mode == "MIX" else None,
            },
        )
        if not to_process:
            return 0

        if self.mode == "ANNUAL_REFRESH":
            self._run_annual_refresh(to_process)
        elif self.mode == "MIX":
            self._run_mixed(to_process)
        else:
            self._run_commitment_window(to_process)
        return len(to_process)

    def _run_commitment_window(self, items: list[dict]) -> None:
        for item in items:
            self._process_item(item, mode="COMMITMENT_WINDOW", run_attempt=1)
            self._sleep_between_hits()

    def _run_annual_refresh(self, items: list[dict]) -> None:
        queue = deque([{"item": it, "run_attempt": 1} for it in items])
        while queue:
            entry = queue.popleft()
            should_retry = self._process_item(
                entry["item"], mode="ANNUAL_REFRESH", run_attempt=entry["run_attempt"]
            )
            if should_retry and entry["run_attempt"] < 3:
                queue.append(
                    {"item": entry["item"], "run_attempt": entry["run_attempt"] + 1}
                )
            self._sleep_between_hits()

    def _run_mixed(self, items: list[dict]) -> None:
        commitment_items = [i for i in items if i.get("mode") == "COMMITMENT_WINDOW"]
        annual_items = [i for i in items if i.get("mode") == "ANNUAL_REFRESH"]
        log.info(
            "mix_mode_split",
            extra={
                "extra_commitment_window_items": len(commitment_items),
                "extra_annual_refresh_items": len(annual_items),
            },
        )
        if commitment_items:
            self._run_commitment_window(commitment_items)
        if annual_items:
            self._run_annual_refresh(annual_items)

    def _process_item(self, item: dict, mode: str, run_attempt: int = 1) -> bool:
        doc = item.get("doc") or {}
        idx = item.get("number_idx")
        service_id = item.get("service_id")

        if service_id is None or idx is None:
            log.warning("process_skip_invalid_item", extra={"item": item})
            return False

        numbers = doc.get(CONFIG.NUMBERS_FIELD) or doc.get("numbers_info") or []
        if not isinstance(idx, int) or idx < 0 or idx >= len(numbers):
            log.warning(
                "process_skip_bad_index",
                extra={"serviceId": service_id, "idx": idx, "numbers_len": len(numbers)},
            )
            return False

        info = numbers[idx] or {}

        ico = doc.get("ico") or doc.get("ICO") or info.get("ico")
        if not ico:
            log.warning(
                "process_missing_ico_skip_mysql",
                extra={"serviceId": service_id, "doc_id": doc.get("_id")},
            )
            ico = None

        try:
            result = self.client.fetch(str(service_id))
        except Exception as e:
            log.exception(
                "telekom_fetch_failed",
                extra={
                    "serviceId": service_id,
                    "mode": mode,
                    "run_attempt": run_attempt,
                    "err": str(e),
                },
            )
            try:
                self.mongo.record_attempt(
                    doc_id=doc["_id"],
                    number_idx=idx,
                    mode=mode,
                    status_code=0,
                    has_commitment=False,
                    raw_payload=str(e),
                )
            except Exception:
                log.exception(
                    "mongo_update_failed_after_fetch_error",
                    extra={"serviceId": service_id},
                )
            return False

        status_code = result.status_code
        parsed = result.parsed
        parsed_commitment = parsed.commitment_end_date if parsed else None
        has_commitment = parsed_commitment is not None
        existing_commitment = self.mongo._parse_datetime(
            self.mongo._commitment_raw(info)
        )
        no_commitment_resp = (status_code == 204) or (not has_commitment)

        commitment_to_store = None
        clear_commitment = False
        reset_mode_attempts = False

        if mode == "COMMITMENT_WINDOW":
            if has_commitment and parsed_commitment != existing_commitment:
                commitment_to_store = parsed_commitment
                reset_mode_attempts = True
        else:
            if has_commitment:
                commitment_to_store = parsed_commitment
            else:
                stale_commitment = (
                    existing_commitment is not None
                    and existing_commitment <= datetime.utcnow() - timedelta(days=60)
                )
                if run_attempt >= 3 and stale_commitment and no_commitment_resp:
                    clear_commitment = True

        # Upsert into MySQL only if we have BOTH parsed + ico
        if parsed is not None and ico is not None:
            try:
                self.mysql.upsert_summary(ico=ico, parsed=parsed)
            except Exception as e:
                log.exception(
                    "mysql_upsert_summary_failed",
                    extra={"serviceId": service_id, "ico": ico, "err": str(e)},
                )
        else:
            log.info(
                "skip_mysql_upsert",
                extra={
                    "serviceId": service_id,
                    "ico": ico,
                    "parsed_present": parsed is not None,
                    "mode": mode,
                },
            )

        try:
            self.mongo.record_attempt(
                doc_id=doc["_id"],
                number_idx=idx,
                mode=mode,
                status_code=status_code,
                has_commitment=has_commitment,
                commitment_end_date=commitment_to_store,
                raw_payload=result.raw_text,
                clear_commitment=clear_commitment,
                reset_mode_attempts=reset_mode_attempts,
            )
        except Exception as e:
            log.exception("mongo_update_failed", extra={"serviceId": service_id, "err": str(e)})

        should_retry = False
        if mode == "ANNUAL_REFRESH":
            should_retry = no_commitment_resp and not clear_commitment

        log.info(
            "process_done",
            extra={
                "serviceId": service_id,
                "ico": ico,
                "status_code": status_code,
                "has_commitment": has_commitment,
                "mode": mode,
                "run_attempt": run_attempt,
                "cleared_commitment": clear_commitment,
                "reset_mode_attempts": reset_mode_attempts,
            },
        )

        return should_retry

    def _sleep_between_hits(self) -> None:
        # Pace scraping between 20 and 40 seconds to avoid hammering the API
        base_delay = self.delay_sec or 20.0
        base_delay = min(max(base_delay, 20.0), 40.0)
        jitter = 40.0 - base_delay
        sleep_with_jitter(base_delay, jitter_range=jitter)
