# mongo_repo.py
from __future__ import annotations
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from pymongo import MongoClient, ReturnDocument
from pymongo.collection import Collection

from config import CONFIG

log = logging.getLogger(__name__)


class MongoRepo:
    def __init__(self):
        self.client = MongoClient(CONFIG.MONGO_URI)
        self.db = self.client[CONFIG.MONGO_DB]
        self.col: Collection = self.db[CONFIG.MONGO_COLLECTION]
        self.archive_col: Collection = self.db[CONFIG.MONGO_ARCHIVE_COLLECTION]

    # -------------------- helpers --------------------
    @staticmethod
    def _parse_datetime(value: Any) -> Optional[datetime]:
        """Best-effort parser for datetime fields stored as strings."""
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value.strip():
            cleaned = value.replace("Z", "").strip()
            try:
                return datetime.fromisoformat(cleaned)
            except Exception:
                try:
                    return datetime.strptime(cleaned, "%d.%m.%Y")
                except Exception:
                    return None
        return None

    @staticmethod
    def _commitment_raw(info: Dict[str, Any]) -> Any:
        return info.get("commitment_end_date")

    def _build_root_commitment_fields(
        self,
        numbers: List[Dict[str, Any]],
        now_ts: Optional[datetime] = None,
        processed_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        earliest_dt: Optional[datetime] = None
        earliest_service: Optional[str] = None

        for info in numbers or []:
            if not isinstance(info, dict):
                continue
            commit_dt = self._parse_datetime(self._commitment_raw(info))
            if commit_dt is None:
                continue
            if earliest_dt is None or commit_dt < earliest_dt:
                earliest_dt = commit_dt
                earliest_service = str(
                    info.get("services")
                    or info.get("service")
                    or ""
                ).strip() or None

        processed_at = now_ts or datetime.utcnow()
        fields: Dict[str, Any] = {"update_time": processed_at}
        if processed_mode:
            fields["last_processed_mode"] = processed_mode
            fields["last_processed_at"] = processed_at
            if processed_mode == "COMMITMENT_WINDOW":
                fields["last_commitment_window_processed_at"] = processed_at
            elif processed_mode == "ANNUAL_REFRESH":
                fields["last_annual_refresh_processed_at"] = processed_at
        if earliest_dt is None:
            fields["commitment_end_date"] = None
            fields["service"] = None
            return fields

        fields["commitment_end_date"] = earliest_dt
        fields["service"] = earliest_service
        return fields

    def _sync_root_commitment_fields(
        self,
        doc_id: Any,
        now_ts: Optional[datetime] = None,
        processed_mode: Optional[str] = None,
    ) -> None:
        doc = self.col.find_one({"_id": doc_id}, projection={CONFIG.NUMBERS_FIELD: 1})
        if not doc:
            return
        numbers = doc.get(CONFIG.NUMBERS_FIELD) or []
        set_fields = self._build_root_commitment_fields(
            numbers,
            now_ts=now_ts,
            processed_mode=processed_mode,
        )
        self.col.update_one({"_id": doc_id}, {"$set": set_fields})

    # -------------------- selection by schedule -------------------
    def select_numbers_to_check(
        self,
        mode: str,
        limit: int = 200,
        now: Optional[datetime] = None,
        mix_window_limit: Optional[int] = None,
        mix_annual_limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        mode_upper = (mode or "").upper()
        if mode_upper == "COMMITMENT_WINDOW":
            return self._select_commitment_window(limit=limit, now=now)
        if mode_upper == "ANNUAL_REFRESH":
            return self._select_annual_refresh(limit=limit, now=now)
        if mode_upper == "MIX":
            return self._select_mix(
                limit=limit,
                now=now,
                mix_window_limit=mix_window_limit,
                mix_annual_limit=mix_annual_limit,
            )
        raise ValueError(f"Unknown scraper mode: {mode}")

    def _select_mix(
        self,
        limit: int = 200,
        now: Optional[datetime] = None,
        mix_window_limit: Optional[int] = None,
        mix_annual_limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        total_limit = min(max(int(limit), 0), 200)
        window_cap = min(
            max(int(mix_window_limit or CONFIG.MIX_WINDOW_LIMIT_PER_CYCLE), 0),
            total_limit,
        )
        annual_cap = min(
            max(int(mix_annual_limit or CONFIG.MIX_ANNUAL_LIMIT_PER_CYCLE), 0),
            total_limit,
        )

        window_items = self._select_commitment_window(limit=window_cap, now=now)
        annual_items = self._select_annual_refresh(limit=total_limit, now=now)

        selected: List[Dict[str, Any]] = []
        seen: set[tuple[Any, int]] = set()

        for item in window_items:
            key = ((item.get("doc") or {}).get("_id"), int(item.get("number_idx", -1)))
            if key in seen:
                continue
            seen.add(key)
            selected.append(item)
            if len(selected) >= total_limit:
                return selected

        added_annual = 0
        for item in annual_items:
            if added_annual >= annual_cap or len(selected) >= total_limit:
                break
            key = ((item.get("doc") or {}).get("_id"), int(item.get("number_idx", -1)))
            if key in seen:
                continue
            seen.add(key)
            selected.append(item)
            added_annual += 1

        return selected

    def _select_commitment_window(
        self, limit: int = 200, now: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Query A: monitor records around their commitment date."""
        now = now or datetime.utcnow()
        limit = min(max(int(limit), 0), 200)
        weekly_cutoff = now - timedelta(days=7)

        cursor = self.col.find(
            {
                CONFIG.NUMBERS_FIELD: {
                    "$elemMatch": {
                        "$or": [
                            {"commitment_end_date": {"$exists": True}},
                        ]
                    }
                }
            },
            projection={"_id": 1, CONFIG.NUMBERS_FIELD: 1, "ico": 1},
        )

        candidates: List[Dict[str, Any]] = []
        for doc in cursor:
            numbers = doc.get(CONFIG.NUMBERS_FIELD) or []
            for idx, info in enumerate(numbers):
                service_id = str(
                    info.get(CONFIG.NUMBER_KEY)
                    or info.get("serviceId")
                    or info.get("number")
                    or ""
                )
                if not service_id:
                    continue

                commit_raw = self._commitment_raw(info)
                commit_dt = self._parse_datetime(commit_raw)
                if commit_raw in (None, "", []):
                    continue
                if not commit_dt:
                    continue

                # Require now between commitment_end_date - 3 months and +1 month
                if not (commit_dt - timedelta(days=90) <= now <= commit_dt + timedelta(days=30)):
                    continue

                last_attempt = self._parse_datetime(
                    info.get("last_attempt_at") or info.get("update_time")
                )
                if last_attempt and last_attempt > weekly_cutoff:
                    continue

                candidates.append(
                    {
                        "doc": doc,
                        "number_idx": idx,
                        "service_id": service_id,
                        "commitment_end_date": commit_dt,
                        "last_attempt_at": last_attempt,
                        "mode": "COMMITMENT_WINDOW",
                    }
                )

        candidates.sort(
            key=lambda c: (
                c["commitment_end_date"],
                c["last_attempt_at"] or datetime.fromtimestamp(0),
            )
        )
        return candidates[:limit]

    def _select_annual_refresh(
        self, limit: int = 200, now: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Query B: annual refresh for missing/old commitments."""
        now = now or datetime.utcnow()
        limit = min(max(int(limit), 0), 200)

        annual_cutoff = now - timedelta(days=365)
        old_commit_cutoff = now - timedelta(days=60)

        cursor = self.col.find(
            {CONFIG.NUMBERS_FIELD: {"$elemMatch": {}}},
            projection={"_id": 1, CONFIG.NUMBERS_FIELD: 1, "ico": 1},
        )

        candidates: List[Dict[str, Any]] = []
        for doc in cursor:
            numbers = doc.get(CONFIG.NUMBERS_FIELD) or []
            for idx, info in enumerate(numbers):
                service_id = str(
                    info.get(CONFIG.NUMBER_KEY)
                    or info.get("serviceId")
                    or info.get("number")
                    or ""
                )
                if not service_id:
                    continue

                commit_raw = self._commitment_raw(info)
                commit_dt = self._parse_datetime(commit_raw)
                has_any_commitment_value = commit_raw not in (None, "", [])

                missing_commitment = not has_any_commitment_value
                old_commitment = commit_dt is not None and commit_dt <= old_commit_cutoff

                if not (missing_commitment or old_commitment):
                    continue

                last_annual = self._parse_datetime(info.get("last_annual_attempt_at"))
                if last_annual and last_annual > annual_cutoff:
                    continue

                candidates.append(
                    {
                        "doc": doc,
                        "number_idx": idx,
                        "service_id": service_id,
                        "commitment_end_date": commit_dt,
                        "last_annual_attempt_at": last_annual,
                        "mode": "ANNUAL_REFRESH",
                    }
                )

        candidates.sort(
            key=lambda c: (
                c["last_annual_attempt_at"] or datetime.fromtimestamp(0),
                c["service_id"],
            )
        )
        return candidates[:limit]

    # -------------------- write backs --------------------
    def record_attempt(
        self,
        doc_id: Any,
        number_idx: int,
        mode: str,
        status_code: int,
        has_commitment: bool,
        commitment_end_date: Any = None,
        raw_payload: Optional[str] = None,
        clear_commitment: bool = False,
        reset_mode_attempts: bool = False,
    ) -> None:
        now_ts = datetime.utcnow()
        mode_key = "commitment_window" if mode.upper() == "COMMITMENT_WINDOW" else "annual"
        normalized_commitment = self._parse_datetime(commitment_end_date)

        base_path = f"{CONFIG.NUMBERS_FIELD}.{number_idx}"
        mode_attempt_field = f"{base_path}.attempts.{mode_key}"

        set_fields: Dict[str, Any] = {
            f"{base_path}.last_attempt_at": now_ts,
            f"{base_path}.last_response_code": status_code,
            f"{base_path}.last_response_has_commitment": has_commitment,
            f"{base_path}.attempt_source": mode_key,
            f"{base_path}.last_processed_mode": mode.upper(),
            f"{base_path}.last_processed_at": now_ts,
            f"{base_path}.update_time": now_ts,
            f"{base_path}.last_response_payload": (raw_payload or "")[: CONFIG.ARCHIVE_SNIPPET_LEN],
        }
        inc_fields: Dict[str, int] = {}

        if mode.upper() == "COMMITMENT_WINDOW":
            set_fields[f"{base_path}.last_commitment_window_attempt_at"] = now_ts
        else:
            set_fields[f"{base_path}.last_annual_attempt_at"] = now_ts

        if normalized_commitment is not None and not clear_commitment:
            set_fields[f"{base_path}.commitment_end_date"] = normalized_commitment

        if clear_commitment:
            set_fields[f"{base_path}.commitment_end_date"] = None

        if reset_mode_attempts:
            set_fields[mode_attempt_field] = 1
        else:
            inc_fields[mode_attempt_field] = 1

        update: Dict[str, Any] = {"$set": set_fields}
        if inc_fields:
            update["$inc"] = inc_fields

        self.col.update_one({"_id": doc_id}, update)
        self._sync_root_commitment_fields(
            doc_id=doc_id,
            now_ts=now_ts,
            processed_mode=mode.upper(),
        )

    def upsert_number_response(
        self,
        base_filter: Dict[str, Any],
        number_idx: int,
        status_code: int,
        raw_text: str,
    ) -> Dict[str, Any]:
        now_ts = datetime.utcnow()
        update = {
            "$set": {
                f"{CONFIG.NUMBERS_FIELD}.{number_idx}.response_code": status_code,
                f"{CONFIG.NUMBERS_FIELD}.{number_idx}.response_content": raw_text,
                f"{CONFIG.NUMBERS_FIELD}.{number_idx}.update_time": now_ts,
            }
        }
        doc = self.col.find_one_and_update(
            base_filter,
            update,
            return_document=ReturnDocument.AFTER,
        )
        if doc and doc.get("_id") is not None:
            self._sync_root_commitment_fields(
                doc_id=doc["_id"],
                now_ts=now_ts,
                processed_mode="RESPONSE_UPDATE",
            )
        return doc

    def archive_snapshot(
        self,
        base_filter: Dict[str, Any],
        number_value: str,
        status_code: int,
        raw_text: str,
    ) -> None:
        snippet = (raw_text or "")[: CONFIG.ARCHIVE_SNIPPET_LEN]
        doc = {
            **base_filter,
            "number": number_value,
            "response_code": status_code,
            "response_content": snippet,
            "update_time": datetime.utcnow(),
        }
        self.archive_col.insert_one(doc)
