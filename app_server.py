#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import sqlite3
import ssl
import subprocess
import tempfile
import threading
from datetime import date, datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

ROOT_DIR = Path(__file__).resolve().parent
DATA_FILE = ROOT_DIR / "data.json"
DB_FILE = ROOT_DIR / "fasting.db"
CHAT_FILE = ROOT_DIR / "chat_memory.json"
CHECKIN_HISTORY_FILE = ROOT_DIR / "checkin_history.jsonl"
REPORTS_DIR = ROOT_DIR / "reports"
BACKUPS_DIR = ROOT_DIR / "backups"

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
THINK_BLOCK_RE = re.compile(r"<think>[\s\S]*?</think>\s*", re.IGNORECASE)
TOKEN_RE = re.compile(r"[a-z0-9]{3,}")

DATA_LOCK = threading.RLock()
CHAT_LOCK = threading.Lock()
REPORTS_LOCK = threading.Lock()
SYNC_LOCK = threading.Lock()
AUTO_SYNC_STATE_LOCK = threading.Lock()
AUTO_SYNC_STOP_EVENT = threading.Event()

DEFAULT_MINIMAX_BASE_URL = "https://api.minimax.io/v1"
DEFAULT_MINIMAX_MODEL = "MiniMax-M2.5"
CHAT_CONTEXT_MESSAGES = 60
CHAT_HISTORY_LIMIT = 1000
REPORT_SNIPPET_CHARS = 2200
REPORT_HEAD_CHARS = 16000
REPORTS_CONTEXT_LIMIT = 4
REPORTS_INDEX_LIMIT = 40

MISSING = object()

DEFAULT_CYCLE = 1
DEFAULT_FAST = {
    "start": "",
    "goal_days": 11,
    "end": "",
}
DEFAULT_REFEED = {
    "start": "",
    "end": "",
    "goal_days": 10,
}
DEFAULT_BASELINE = {
    "period": "",
    "avg_total_calories": None,
    "avg_active_calories": None,
    "avg_steps": None,
    "note": "",
}
DEFAULT_PROFILE = {"height_cm": 174}
DEFAULT_SNAPSHOT = {
    "baseline": copy.deepcopy(DEFAULT_BASELINE),
    "body_composition": [],
    "cycle": DEFAULT_CYCLE,
    "day_guide": {},
    "fast": copy.deepcopy(DEFAULT_FAST),
    "log": [],
    "measurements": [],
    "previous_cycles": [],
    "profile": copy.deepcopy(DEFAULT_PROFILE),
    "refeed": copy.deepcopy(DEFAULT_REFEED),
    "refeed_measurements": [],
}

META_DEFAULTS = {
    "baseline": copy.deepcopy(DEFAULT_BASELINE),
    "body_composition": [],
    "cycle": DEFAULT_CYCLE,
    "day_guide": {},
    "fast": copy.deepcopy(DEFAULT_FAST),
    "log": [],
    "previous_cycles": [],
    "profile": copy.deepcopy(DEFAULT_PROFILE),
    "refeed": copy.deepcopy(DEFAULT_REFEED),
    "refeed_measurements": [],
}

REPORTS_CACHE_SIGNATURE = ""
REPORTS_CACHE_ITEMS: list[dict] = []
AUTO_SYNC_THREAD: threading.Thread | None = None
AUTO_SYNC_NEXT_RUN_AT: str | None = None
AUTO_SYNC_LAST_RUN_AT: str | None = None
AUTO_SYNC_LAST_ERROR: str | None = None


def env_int(name: str, default: int, min_value: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_value, value)


AUTO_SYNC_ENABLED = (os.environ.get("OURA_AUTO_SYNC") or "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
AUTO_SYNC_INTERVAL_SECONDS = env_int("OURA_AUTO_SYNC_INTERVAL_SECONDS", 7200, 300)
AUTO_SYNC_INITIAL_DELAY_SECONDS = env_int("OURA_AUTO_SYNC_INITIAL_DELAY_SECONDS", 30, 0)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def append_checkin_history(entry: dict) -> None:
    payload = {"timestamp": now_iso(), **entry}
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    try:
        with CHECKIN_HISTORY_FILE.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        # Check-in should still succeed even if audit log append fails.
        pass


def backup_db_daily_if_needed() -> None:
    if not DB_FILE.exists():
        return
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    daily = BACKUPS_DIR / f"fasting-{datetime.now().strftime('%Y-%m-%d')}.db"
    if not daily.exists():
        shutil.copy2(DB_FILE, daily)


def backup_source_data_for_migration() -> None:
    if not DATA_FILE.exists():
        return
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    target = BACKUPS_DIR / f"data-pre-sqlite-migration-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    shutil.copy2(DATA_FILE, target)


def parse_json_text(raw: str, default: object) -> object:
    try:
        return json.loads(raw)
    except Exception:
        return copy.deepcopy(default)


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_meta (
          key TEXT PRIMARY KEY,
          value_json TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS measurements (
          date TEXT PRIMARY KEY,
          day INTEGER NOT NULL,
          weight_kg REAL,
          weight_change_kg REAL,
          water_liters REAL,
          oura_json TEXT NOT NULL DEFAULT '{}',
          notes TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          provider TEXT NOT NULL,
          source TEXT NOT NULL,
          started_at TEXT NOT NULL,
          finished_at TEXT,
          status TEXT NOT NULL,
          start_date TEXT,
          end_date TEXT,
          updated_days INTEGER DEFAULT 0,
          message TEXT
        )
        """
    )


def db_get_meta_unlocked(conn: sqlite3.Connection, key: str, default: object) -> object:
    row = conn.execute("SELECT value_json FROM app_meta WHERE key = ?", (key,)).fetchone()
    if not row:
        return copy.deepcopy(default)
    return parse_json_text(row["value_json"], default)


def db_set_meta_unlocked(conn: sqlite3.Connection, key: str, value: object) -> None:
    conn.execute(
        """
        INSERT INTO app_meta (key, value_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
          value_json = excluded.value_json,
          updated_at = excluded.updated_at
        """,
        (key, json.dumps(value, ensure_ascii=False), now_iso()),
    )


def default_snapshot() -> dict:
    return copy.deepcopy(DEFAULT_SNAPSHOT)


def read_data_file() -> dict:
    if not DATA_FILE.exists():
        return default_snapshot()
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return default_snapshot()
    if not isinstance(payload, dict):
        return default_snapshot()
    return payload


def load_measurements_unlocked(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT date, day, weight_kg, weight_change_kg, water_liters, oura_json, notes FROM measurements ORDER BY date"
    ).fetchall()
    items: list[dict] = []
    for row in rows:
        oura_payload = parse_json_text(row["oura_json"] or "{}", {})
        if not isinstance(oura_payload, dict):
            oura_payload = {}
        items.append(
            {
                "date": row["date"],
                "day": int(row["day"]),
                "weight_kg": row["weight_kg"],
                "weight_change_kg": row["weight_change_kg"],
                "oura": oura_payload,
                "notes": row["notes"] or "",
                "water_liters": row["water_liters"],
            }
        )
    return items


def build_snapshot_unlocked(conn: sqlite3.Connection) -> dict:
    snapshot = default_snapshot()
    for key, default in META_DEFAULTS.items():
        snapshot[key] = db_get_meta_unlocked(conn, key, default)
    snapshot["measurements"] = load_measurements_unlocked(conn)

    if not isinstance(snapshot.get("profile"), dict):
        snapshot["profile"] = copy.deepcopy(DEFAULT_PROFILE)
    if not isinstance(snapshot["profile"].get("height_cm"), (int, float)):
        snapshot["profile"]["height_cm"] = DEFAULT_PROFILE["height_cm"]
    snapshot["profile"]["height_cm"] = int(round(float(snapshot["profile"]["height_cm"])))

    return snapshot


def write_snapshot_cache_unlocked(conn: sqlite3.Connection) -> dict:
    snapshot = build_snapshot_unlocked(conn)
    atomic_write_json(DATA_FILE, snapshot)
    return snapshot


def recalculate_weight_changes_unlocked(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT date, weight_kg FROM measurements ORDER BY date").fetchall()
    previous_weight: float | None = None
    for row in rows:
        date_key = row["date"]
        weight = row["weight_kg"]
        if weight is None:
            conn.execute("UPDATE measurements SET weight_change_kg = ?, updated_at = ? WHERE date = ?", (None, now_iso(), date_key))
            continue
        rounded_weight = round(float(weight), 1)
        change = None if previous_weight is None else round(rounded_weight - previous_weight, 1)
        conn.execute(
            "UPDATE measurements SET weight_kg = ?, weight_change_kg = ?, updated_at = ? WHERE date = ?",
            (rounded_weight, change, now_iso(), date_key),
        )
        previous_weight = rounded_weight


def compute_day_number_from_fast(fast_start_raw: str, date_str: str) -> int:
    try:
        fast_start = (fast_start_raw or "").split("T")[0]
        start_dt = datetime.strptime(fast_start, "%Y-%m-%d").date()
        entry_dt = datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return 1
    return max(1, (entry_dt - start_dt).days + 1)


def fast_start_unlocked(conn: sqlite3.Connection) -> str:
    fast_obj = db_get_meta_unlocked(conn, "fast", DEFAULT_FAST)
    if not isinstance(fast_obj, dict):
        return ""
    return str(fast_obj.get("start") or "")


def ensure_storage_ready() -> None:
    with DATA_LOCK:
        conn = db_connect()
        try:
            init_db(conn)
            has_schema = conn.execute("SELECT 1 FROM app_meta WHERE key = 'schema_version'").fetchone() is not None
            if not has_schema:
                source = read_data_file()
                backup_source_data_for_migration()
                with conn:
                    for key, default in META_DEFAULTS.items():
                        db_set_meta_unlocked(conn, key, source.get(key, copy.deepcopy(default)))
                    conn.execute("DELETE FROM measurements")
                    for item in sorted(source.get("measurements", []), key=lambda x: str((x or {}).get("date", ""))):
                        if not isinstance(item, dict):
                            continue
                        day = int(item.get("day") or 1)
                        date_key = str(item.get("date") or "")
                        if not DATE_RE.match(date_key):
                            continue
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO measurements
                            (date, day, weight_kg, weight_change_kg, water_liters, oura_json, notes, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                date_key,
                                day,
                                item.get("weight_kg"),
                                item.get("weight_change_kg"),
                                item.get("water_liters"),
                                json.dumps(item.get("oura") or {}, ensure_ascii=False),
                                str(item.get("notes") or ""),
                                now_iso(),
                            ),
                        )
                    recalculate_weight_changes_unlocked(conn)
                    db_set_meta_unlocked(conn, "schema_version", 1)
                    db_set_meta_unlocked(conn, "migrated_at", now_iso())

            write_snapshot_cache_unlocked(conn)
        finally:
            conn.close()
    backup_db_daily_if_needed()


def create_sync_run(provider: str, source: str, start_date: str, end_date: str) -> int:
    with DATA_LOCK:
        conn = db_connect()
        try:
            with conn:
                cur = conn.execute(
                    """
                    INSERT INTO sync_runs (provider, source, started_at, status, start_date, end_date, updated_days, message)
                    VALUES (?, ?, ?, 'running', ?, ?, 0, '')
                    """,
                    (provider, source, now_iso(), start_date, end_date),
                )
                return int(cur.lastrowid)
        finally:
            conn.close()


def finish_sync_run(run_id: int, status: str, message: str, updated_days: int) -> None:
    with DATA_LOCK:
        conn = db_connect()
        try:
            with conn:
                conn.execute(
                    """
                    UPDATE sync_runs
                    SET finished_at = ?, status = ?, message = ?, updated_days = ?
                    WHERE id = ?
                    """,
                    (now_iso(), status, message[:800], updated_days, run_id),
                )
        finally:
            conn.close()


def latest_sync_run(provider: str = "oura") -> dict | None:
    with DATA_LOCK:
        conn = db_connect()
        try:
            row = conn.execute(
                """
                SELECT id, provider, source, started_at, finished_at, status, start_date, end_date, updated_days, message
                FROM sync_runs
                WHERE provider = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (provider,),
            ).fetchone()
            if not row:
                return None
            return {
                "id": int(row["id"]),
                "provider": row["provider"],
                "source": row["source"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "status": row["status"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "updated_days": int(row["updated_days"] or 0),
                "message": row["message"] or "",
            }
        finally:
            conn.close()


def read_data_snapshot() -> dict:
    with DATA_LOCK:
        conn = db_connect()
        try:
            return build_snapshot_unlocked(conn)
        finally:
            conn.close()


def upsert_measurement_unlocked(
    conn: sqlite3.Connection,
    date_key: str,
    *,
    weight: object = MISSING,
    water: object = MISSING,
    oura_payload: dict | None = None,
    notes: object = MISSING,
    day_override: int | None = None,
) -> dict:
    row = conn.execute(
        "SELECT date, day, weight_kg, weight_change_kg, water_liters, oura_json, notes FROM measurements WHERE date = ?",
        (date_key,),
    ).fetchone()

    fast_start_raw = fast_start_unlocked(conn)
    computed_day = day_override if day_override is not None else compute_day_number_from_fast(fast_start_raw, date_key)
    if computed_day < 1:
        computed_day = 1

    if row is None:
        current = {
            "date": date_key,
            "day": computed_day,
            "weight_kg": None,
            "weight_change_kg": None,
            "water_liters": None,
            "oura": {},
            "notes": "",
        }
    else:
        current = {
            "date": row["date"],
            "day": int(row["day"]),
            "weight_kg": row["weight_kg"],
            "weight_change_kg": row["weight_change_kg"],
            "water_liters": row["water_liters"],
            "oura": parse_json_text(row["oura_json"] or "{}", {}),
            "notes": row["notes"] or "",
        }
        if not isinstance(current["oura"], dict):
            current["oura"] = {}

    current["day"] = computed_day

    if weight is not MISSING:
        current["weight_kg"] = weight
    if water is not MISSING:
        current["water_liters"] = water
    if oura_payload is not None:
        current["oura"] = merge_non_null_dict(current.get("oura") or {}, oura_payload)
    if notes is not MISSING:
        current["notes"] = str(notes or "")

    conn.execute(
        """
        INSERT OR REPLACE INTO measurements
        (date, day, weight_kg, weight_change_kg, water_liters, oura_json, notes, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            current["date"],
            current["day"],
            current["weight_kg"],
            current["weight_change_kg"],
            current["water_liters"],
            json.dumps(current["oura"], ensure_ascii=False),
            current["notes"],
            now_iso(),
        ),
    )
    return current


def merge_non_null_dict(existing: dict, incoming: dict) -> dict:
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        if isinstance(value, dict):
            existing_nested = merged.get(key) if isinstance(merged.get(key), dict) else {}
            merged[key] = merge_non_null_dict(existing_nested, value)
            continue
        if value is not None:
            merged[key] = value
    return merged


def upsert_checkin(payload: dict) -> dict:
    date_key = payload.get("date")
    if not isinstance(date_key, str) or not DATE_RE.match(date_key):
        raise ValueError("date must be YYYY-MM-DD")
    try:
        datetime.strptime(date_key, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError("date must be a valid calendar date (YYYY-MM-DD)") from e

    weight_raw = payload.get("weight_kg", MISSING)
    water_raw = payload.get("water_liters", MISSING)

    weight_value = MISSING
    water_value = MISSING

    if weight_raw is not MISSING:
        if weight_raw is None:
            weight_value = None
        else:
            weight_value = round(float(weight_raw), 1)
            if weight_value < 30 or weight_value > 300:
                raise ValueError("weight_kg must be between 30 and 300")

    if water_raw is not MISSING:
        if water_raw is None:
            water_value = None
        else:
            water_value = round(float(water_raw), 1)
            if water_value < 0 or water_value > 20:
                raise ValueError("water_liters must be between 0 and 20")

    with DATA_LOCK:
        conn = db_connect()
        try:
            existing = conn.execute(
                "SELECT weight_kg, water_liters FROM measurements WHERE date = ?",
                (date_key,),
            ).fetchone()

            with conn:
                measurement = upsert_measurement_unlocked(
                    conn,
                    date_key,
                    weight=weight_value,
                    water=water_value,
                )
                recalculate_weight_changes_unlocked(conn)

            snapshot = write_snapshot_cache_unlocked(conn)
        finally:
            conn.close()

    backup_db_daily_if_needed()

    append_checkin_history(
        {
            "source": "api/checkin",
            "date": date_key,
            "day": measurement["day"],
            "created": existing is None,
            "previous_weight_kg": existing["weight_kg"] if existing else None,
            "previous_water_liters": existing["water_liters"] if existing else None,
            "weight_kg": measurement["weight_kg"],
            "water_liters": measurement["water_liters"],
        }
    )

    return {
        "ok": True,
        "date": date_key,
        "weight_kg": measurement["weight_kg"],
        "water_liters": measurement["water_liters"],
        "day": measurement["day"],
        "measurements": len(snapshot.get("measurements", [])),
    }


def upsert_profile(payload: dict) -> dict:
    height_cm = payload.get("height_cm", None)
    if height_cm is not None:
        height_cm = int(round(float(height_cm)))
        if height_cm < 120 or height_cm > 230:
            raise ValueError("height_cm must be between 120 and 230")

    with DATA_LOCK:
        conn = db_connect()
        try:
            with conn:
                profile = db_get_meta_unlocked(conn, "profile", DEFAULT_PROFILE)
                if not isinstance(profile, dict):
                    profile = copy.deepcopy(DEFAULT_PROFILE)
                if height_cm is not None:
                    profile["height_cm"] = height_cm
                db_set_meta_unlocked(conn, "profile", profile)
            write_snapshot_cache_unlocked(conn)
        finally:
            conn.close()

    backup_db_daily_if_needed()
    return {"ok": True, "height_cm": int(profile.get("height_cm", DEFAULT_PROFILE["height_cm"]))}


def resolve_oura_token(override: str | None = None) -> str:
    if override and str(override).strip():
        return str(override).strip()

    env_key = (os.environ.get("OURA_TOKEN") or "").strip()
    if env_key:
        return env_key

    for token_file in (ROOT_DIR / ".oura_token", ROOT_DIR / ".oura_key"):
        if token_file.exists():
            token = token_file.read_text(encoding="utf-8").strip()
            if token:
                return token

    return ""


def oura_ssl_context() -> ssl.SSLContext | None:
    if (
        (os.environ.get("OURA_INSECURE_SKIP_VERIFY") or "").strip().lower() in ("1", "true", "yes", "on")
        or (os.environ.get("MINIMAX_INSECURE_SKIP_VERIFY") or "").strip().lower() in ("1", "true", "yes", "on")
    ):
        return ssl._create_unverified_context()

    ca_file = (
        (os.environ.get("OURA_CA_FILE") or "").strip()
        or (os.environ.get("MINIMAX_CA_FILE") or "").strip()
        or (os.environ.get("SSL_CERT_FILE") or "").strip()
    )
    if ca_file:
        return ssl.create_default_context(cafile=ca_file)
    return None


def oura_request(path: str, token: str, params: dict[str, str] | None = None) -> dict:
    query = f"?{urlencode(params)}" if params else ""
    req = Request(
        f"https://api.ouraring.com/v2/usercollection/{path}{query}",
        method="GET",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urlopen(req, timeout=60, context=oura_ssl_context()) as resp:
            body = resp.read().decode("utf-8")
    except HTTPError as e:
        details = ""
        try:
            details = e.read().decode("utf-8")
        except Exception:
            details = str(e)
        raise RuntimeError(f"Oura API error ({e.code}): {details[:260]}") from e
    except URLError as e:
        raise RuntimeError(f"Could not reach Oura API: {e.reason}") from e

    try:
        parsed = json.loads(body)
    except Exception as e:
        raise RuntimeError("Oura API returned invalid JSON") from e
    if not isinstance(parsed, dict):
        raise RuntimeError("Oura API returned unexpected payload")
    return parsed


def validate_oura_token(token: str) -> None:
    payload = oura_request("personal_info", token)
    # personal_info returns a direct profile object (not wrapped in "data").
    if not isinstance(payload, dict) or not payload.get("id"):
        raise RuntimeError("Oura authentication failed. Verify token in .oura_token")


def parse_date_or_raise(name: str, value: str) -> str:
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise ValueError(f"{name} must be YYYY-MM-DD")
    datetime.strptime(value, "%Y-%m-%d")
    return value


def as_number(value: object, digits: int | None = None) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except Exception:
        return None
    if digits is None:
        return out
    return round(out, digits)


def as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except Exception:
        return None


def collect_days(*datasets: list[dict]) -> list[str]:
    days: set[str] = set()
    for dataset in datasets:
        for item in dataset:
            if not isinstance(item, dict):
                continue
            day = item.get("day")
            if isinstance(day, str) and DATE_RE.match(day):
                days.add(day)
    return sorted(days)


def by_day(dataset: list[dict], day: str, predicate: callable | None = None) -> dict | None:
    for item in dataset:
        if not isinstance(item, dict):
            continue
        if item.get("day") != day:
            continue
        if predicate and not predicate(item):
            continue
        return item
    return None


def parse_iso_datetime(raw: str | None) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def format_time_12h(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def ensure_sleep_log_entries(log_entries: list[dict], day: str, fast_start_raw: str, sleep_record: dict | None) -> list[dict]:
    if not sleep_record:
        return log_entries

    bedtime_raw = sleep_record.get("bedtime_start")
    wake_raw = sleep_record.get("bedtime_end")
    total_sec = as_int(sleep_record.get("total_sleep_duration")) or 0

    bedtime_dt = parse_iso_datetime(str(bedtime_raw) if bedtime_raw is not None else None)
    wake_dt = parse_iso_datetime(str(wake_raw) if wake_raw is not None else None)

    if bedtime_dt is None or wake_dt is None:
        return log_entries

    bedtime_date = bedtime_dt.date().isoformat()
    bedtime_day = compute_day_number_from_fast(fast_start_raw, bedtime_date)
    wake_day = compute_day_number_from_fast(fast_start_raw, day)

    bedtime_msg = f"Bedtime: {format_time_12h(bedtime_dt)}"
    wake_msg = f"Woke up: {format_time_12h(wake_dt)} ({round(total_sec / 3600, 1)} hrs sleep)"

    has_bedtime = any(
        isinstance(item, dict)
        and item.get("date") == bedtime_date
        and item.get("type") == "sleep"
        and "Bedtime" in str(item.get("message") or "")
        for item in log_entries
    )
    has_wake = any(
        isinstance(item, dict)
        and item.get("date") == day
        and item.get("type") == "sleep"
        and "Woke" in str(item.get("message") or "")
        for item in log_entries
    )

    updated = list(log_entries)
    if not has_bedtime:
        updated.append({"date": bedtime_date, "day": bedtime_day, "type": "sleep", "message": bedtime_msg})
    if not has_wake:
        updated.append({"date": day, "day": wake_day, "type": "sleep", "message": wake_msg})

    updated.sort(key=lambda item: (str(item.get("date", "")), str(item.get("type", ""))))
    return updated


def upsert_refeed_oura_entry(
    refeed_measurements: list[dict],
    day: str,
    refeed_day: int,
    oura_payload: dict,
) -> list[dict]:
    updated = [m for m in refeed_measurements if isinstance(m, dict)]
    existing = next((m for m in updated if m.get("date") == day), None)
    if existing is None:
        updated.append(
            {
                "date": day,
                "refeed_day": refeed_day,
                "meals": [],
                "total_calories": None,
                "protein_g": None,
                "carbs_g": None,
                "fat_g": None,
                "weight_kg": None,
                "digestion_status": None,
                "energy_level": None,
                "sleep_quality": None,
                "notes": "",
                "oura": oura_payload,
            }
        )
    else:
        existing["refeed_day"] = refeed_day
        existing["oura"] = oura_payload

    updated.sort(key=lambda m: str(m.get("date", "")))
    return updated


def build_oura_day_payload(
    day: str,
    sleep_summary_rows: list[dict],
    sleep_detail_rows: list[dict],
    readiness_rows: list[dict],
    activity_rows: list[dict],
    stress_rows: list[dict],
) -> tuple[dict, dict | None]:
    sleep_summary = by_day(sleep_summary_rows, day)
    readiness = by_day(readiness_rows, day)
    activity = by_day(activity_rows, day)
    stress = by_day(stress_rows, day)
    sleep_record = by_day(
        sleep_detail_rows,
        day,
        predicate=lambda row: str(row.get("type") or "") == "long_sleep",
    )

    sleep_score = as_int((sleep_summary or {}).get("score"))
    readiness_score = as_int((readiness or {}).get("score"))
    activity_score = as_int((activity or {}).get("score"))

    steps = as_int((activity or {}).get("steps"))
    total_calories = as_int((activity or {}).get("total_calories"))
    active_calories = as_int((activity or {}).get("active_calories"))

    temp_dev = as_number((readiness or {}).get("temperature_deviation"), 2)
    hrv_balance = as_int(((readiness or {}).get("contributors") or {}).get("hrv_balance"))

    sleep_payload = None
    if sleep_record:
        total_sleep_sec = as_int(sleep_record.get("total_sleep_duration")) or 0
        deep_sec = as_int(sleep_record.get("deep_sleep_duration")) or 0
        rem_sec = as_int(sleep_record.get("rem_sleep_duration")) or 0
        light_sec = as_int(sleep_record.get("light_sleep_duration")) or 0

        bedtime = sleep_record.get("bedtime_start")
        wake_time = sleep_record.get("bedtime_end")

        if total_sleep_sec > 0 and bedtime:
            sleep_payload = {
                "bedtime": bedtime,
                "wake_time": wake_time,
                "total_hours": round(total_sleep_sec / 3600, 1),
                "deep_mins": int(deep_sec / 60),
                "rem_mins": int(rem_sec / 60),
                "light_mins": int(light_sec / 60),
                "efficiency": as_int(sleep_record.get("efficiency")),
                "lowest_hr": as_int(sleep_record.get("lowest_heart_rate")),
                "avg_hrv": as_int(sleep_record.get("average_hrv")),
            }

    stress_high = as_int((stress or {}).get("stress_high")) or 0
    recovery_high = as_int((stress or {}).get("recovery_high")) or 0
    stress_payload = {
        "summary": (stress or {}).get("day_summary") or None,
        "stress_mins": int(stress_high / 60),
        "recovery_mins": int(recovery_high / 60),
    }

    return (
        {
            "sleep_score": sleep_score,
            "readiness_score": readiness_score,
            "activity_score": activity_score,
            "steps": steps,
            "total_calories": total_calories,
            "active_calories": active_calories,
            "hrv_balance": hrv_balance,
            "body_temp_deviation": temp_dev,
            "sleep": sleep_payload,
            "stress": stress_payload,
        },
        sleep_record,
    )


def sync_oura_data(
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    token_override: str | None = None,
    source: str = "manual",
) -> dict:
    if not SYNC_LOCK.acquire(blocking=False):
        raise RuntimeError("Oura sync is already running.")

    run_id = 0
    updated_days = 0
    try:
        if start_date:
            start_date = parse_date_or_raise("start_date", start_date)
        if end_date:
            end_date = parse_date_or_raise("end_date", end_date)

        with DATA_LOCK:
            conn = db_connect()
            try:
                fast_obj = db_get_meta_unlocked(conn, "fast", DEFAULT_FAST)
                fast_start = str((fast_obj or {}).get("start") or "")
            finally:
                conn.close()

        if not start_date:
            inferred = (fast_start or "").split("T")[0]
            start_date = inferred if DATE_RE.match(inferred) else date.today().isoformat()
        if not end_date:
            end_date = date.today().isoformat()

        start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        if end_dt < start_dt:
            raise ValueError("end_date cannot be before start_date")

        run_id = create_sync_run("oura", source, start_date, end_date)

        token = resolve_oura_token(token_override)
        if not token:
            raise RuntimeError("Oura token is not configured. Set OURA_TOKEN or create .oura_token")

        validate_oura_token(token)

        # Oura endpoints are inconsistent on end_date semantics:
        # daily_activity/sleep can behave as end-exclusive, while others are inclusive.
        # Query one extra day and then filter rows strictly to [start_date, end_date].
        fetch_end_date = (end_dt + timedelta(days=1)).isoformat()
        params = {"start_date": start_date, "end_date": fetch_end_date}
        sleep_summary = oura_request("daily_sleep", token, params).get("data", []) or []
        sleep_detail = oura_request("sleep", token, params).get("data", []) or []
        readiness = oura_request("daily_readiness", token, params).get("data", []) or []
        activity = oura_request("daily_activity", token, params).get("data", []) or []
        stress = oura_request("daily_stress", token, params).get("data", []) or []

        days = [
            day
            for day in collect_days(activity, readiness, sleep_summary, stress, sleep_detail)
            if start_date <= day <= end_date
        ]

        with DATA_LOCK:
            conn = db_connect()
            try:
                with conn:
                    fast_start_raw = fast_start_unlocked(conn)
                    log_entries = db_get_meta_unlocked(conn, "log", [])
                    if not isinstance(log_entries, list):
                        log_entries = []

                    refeed_obj = db_get_meta_unlocked(conn, "refeed", DEFAULT_REFEED)
                    refeed_start_raw = str((refeed_obj or {}).get("start") or "")
                    refeed_start = refeed_start_raw.split("T")[0] if refeed_start_raw else ""
                    refeed_measurements = db_get_meta_unlocked(conn, "refeed_measurements", [])
                    if not isinstance(refeed_measurements, list):
                        refeed_measurements = []

                    for day in days:
                        day_num = compute_day_number_from_fast(fast_start_raw, day)
                        oura_payload, sleep_record = build_oura_day_payload(
                            day,
                            sleep_summary,
                            sleep_detail,
                            readiness,
                            activity,
                            stress,
                        )

                        upsert_measurement_unlocked(
                            conn,
                            day,
                            oura_payload=oura_payload,
                            day_override=day_num,
                        )
                        updated_days += 1

                        log_entries = ensure_sleep_log_entries(log_entries, day, fast_start_raw, sleep_record)

                        if refeed_start and day >= refeed_start:
                            refeed_day = compute_day_number_from_fast(refeed_start_raw, day)
                            refeed_measurements = upsert_refeed_oura_entry(
                                refeed_measurements,
                                day,
                                refeed_day,
                                oura_payload,
                            )

                    db_set_meta_unlocked(conn, "log", log_entries)
                    db_set_meta_unlocked(conn, "refeed_measurements", refeed_measurements)
                    recalculate_weight_changes_unlocked(conn)

                write_snapshot_cache_unlocked(conn)
            finally:
                conn.close()

        backup_db_daily_if_needed()

        finish_sync_run(run_id, "success", f"Synced {updated_days} days", updated_days)
        return {
            "ok": True,
            "provider": "oura",
            "source": source,
            "start_date": start_date,
            "end_date": end_date,
            "updated_days": updated_days,
            "days": days,
        }
    except Exception as e:
        if run_id:
            finish_sync_run(run_id, "failed", str(e), updated_days)
        raise
    finally:
        SYNC_LOCK.release()


def set_auto_sync_state(*, next_run: str | None = None, last_run: str | None = None, last_error: str | None = None) -> None:
    global AUTO_SYNC_NEXT_RUN_AT
    global AUTO_SYNC_LAST_RUN_AT
    global AUTO_SYNC_LAST_ERROR
    with AUTO_SYNC_STATE_LOCK:
        if next_run is not None:
            AUTO_SYNC_NEXT_RUN_AT = next_run
        if last_run is not None:
            AUTO_SYNC_LAST_RUN_AT = last_run
        if last_error is not None:
            AUTO_SYNC_LAST_ERROR = last_error


def auto_sync_state_payload() -> dict:
    with AUTO_SYNC_STATE_LOCK:
        return {
            "enabled": AUTO_SYNC_ENABLED,
            "interval_seconds": AUTO_SYNC_INTERVAL_SECONDS,
            "next_run_at": AUTO_SYNC_NEXT_RUN_AT,
            "last_run_at": AUTO_SYNC_LAST_RUN_AT,
            "last_error": AUTO_SYNC_LAST_ERROR,
            "running": SYNC_LOCK.locked(),
        }


def start_auto_sync_thread() -> None:
    global AUTO_SYNC_THREAD
    if not AUTO_SYNC_ENABLED:
        return
    if AUTO_SYNC_THREAD and AUTO_SYNC_THREAD.is_alive():
        return

    def worker() -> None:
        if AUTO_SYNC_INITIAL_DELAY_SECONDS > 0:
            initial_next = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() + AUTO_SYNC_INITIAL_DELAY_SECONDS,
                tz=timezone.utc,
            ).replace(microsecond=0)
            set_auto_sync_state(next_run=initial_next.isoformat().replace("+00:00", "Z"))
            if AUTO_SYNC_STOP_EVENT.wait(AUTO_SYNC_INITIAL_DELAY_SECONDS):
                return

        while not AUTO_SYNC_STOP_EVENT.is_set():
            try:
                if resolve_oura_token():
                    sync_oura_data(source="auto")
                    set_auto_sync_state(last_run=now_iso(), last_error="")
                else:
                    set_auto_sync_state(last_error="Oura token not configured")
            except Exception as e:
                set_auto_sync_state(last_error=str(e)[:300])

            next_run = datetime.now(timezone.utc).timestamp() + AUTO_SYNC_INTERVAL_SECONDS
            set_auto_sync_state(next_run=datetime.fromtimestamp(next_run, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
            if AUTO_SYNC_STOP_EVENT.wait(AUTO_SYNC_INTERVAL_SECONDS):
                return

    AUTO_SYNC_THREAD = threading.Thread(target=worker, name="oura-auto-sync", daemon=True)
    AUTO_SYNC_THREAD.start()


def read_chat_memory_unlocked() -> dict:
    if not CHAT_FILE.exists():
        return {"messages": [], "updated_at": now_iso()}
    try:
        with CHAT_FILE.open("r", encoding="utf-8") as f:
            payload = json.load(f)
            if not isinstance(payload, dict):
                return {"messages": [], "updated_at": now_iso()}
            messages = payload.get("messages")
            if not isinstance(messages, list):
                payload["messages"] = []
            return payload
    except Exception:
        return {"messages": [], "updated_at": now_iso()}


def write_chat_memory_unlocked(payload: dict) -> None:
    atomic_write_json(CHAT_FILE, payload)


def normalize_chat_messages(messages: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
            continue
        normalized.append(
            {
                "role": role,
                "content": content.strip(),
                "timestamp": msg.get("timestamp") if isinstance(msg.get("timestamp"), str) else now_iso(),
            }
        )
    return normalized[-CHAT_HISTORY_LIMIT:]


def github_repo_slug() -> str | None:
    try:
        output = subprocess.check_output(
            ["git", "-C", str(ROOT_DIR), "remote", "get-url", "origin"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return None

    if output.startswith("git@github.com:"):
        slug = output.split("git@github.com:", 1)[1]
    elif output.startswith("https://github.com/"):
        slug = output.split("https://github.com/", 1)[1]
    else:
        return None

    if slug.endswith(".git"):
        slug = slug[:-4]
    return slug.strip("/") or None


def github_ref_name() -> str:
    ref = (os.environ.get("REPORTS_GITHUB_REF") or "main").strip()
    return ref or "main"


def github_report_url(report_name: str) -> str | None:
    slug = github_repo_slug()
    if not slug:
        return None
    return f"https://github.com/{slug}/blob/{github_ref_name()}/reports/{report_name}"


def tokenize(text: str) -> set[str]:
    return set(TOKEN_RE.findall((text or "").lower()))


def normalize_report_text(text: str) -> str:
    compact = re.sub(r"\s+", " ", text.replace("\x00", " ")).strip()
    return compact


def report_catalog_signature(files: list[Path]) -> str:
    parts: list[str] = []
    for file in files:
        try:
            stat = file.stat()
            parts.append(f"{file.name}:{int(stat.st_mtime)}:{stat.st_size}")
        except OSError:
            parts.append(f"{file.name}:missing")
    return "|".join(parts)


def load_reports_catalog() -> list[dict]:
    if not REPORTS_DIR.exists():
        return []

    files = sorted(REPORTS_DIR.glob("*.md"))
    signature = report_catalog_signature(files)

    global REPORTS_CACHE_SIGNATURE
    global REPORTS_CACHE_ITEMS

    with REPORTS_LOCK:
        if signature == REPORTS_CACHE_SIGNATURE:
            return REPORTS_CACHE_ITEMS

        items: list[dict] = []
        for file in files:
            try:
                content = file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            head = content[:REPORT_HEAD_CHARS]
            compact = normalize_report_text(head)
            excerpt = compact[:REPORT_SNIPPET_CHARS]
            file_tokens = tokenize(file.name + " " + compact)
            try:
                modified = file.stat().st_mtime
            except OSError:
                modified = 0.0

            items.append(
                {
                    "name": file.name,
                    "path": f"reports/{file.name}",
                    "github_url": github_report_url(file.name),
                    "excerpt": excerpt,
                    "modified": modified,
                    "tokens": file_tokens,
                }
            )

        REPORTS_CACHE_SIGNATURE = signature
        REPORTS_CACHE_ITEMS = items
        return REPORTS_CACHE_ITEMS


def reports_context_for_query(user_text: str, chat_messages: list[dict]) -> dict:
    catalog = load_reports_catalog()
    if not catalog:
        return {
            "reports_available": 0,
            "reports_directory": "reports/",
            "reports_index": [],
            "relevant_reports": [],
        }

    recent_user_messages = " ".join(
        m.get("content", "")
        for m in chat_messages[-8:]
        if isinstance(m, dict) and m.get("role") == "user"
    )
    query_tokens = tokenize(f"{user_text} {recent_user_messages}")

    ranked: list[tuple[int, float, dict]] = []
    for item in catalog:
        token_hits = len(query_tokens & item["tokens"]) if query_tokens else 0
        name_bonus = 0
        name_lc = item["name"].lower()
        for tok in query_tokens:
            if tok in name_lc:
                name_bonus += 2
        score = token_hits + name_bonus
        ranked.append((score, float(item.get("modified", 0.0)), item))

    ranked.sort(key=lambda x: (x[0], x[1]), reverse=True)

    selected: list[dict] = []
    for score, _, item in ranked:
        if len(selected) >= REPORTS_CONTEXT_LIMIT:
            break
        if query_tokens and score <= 0:
            continue
        selected.append(
            {
                "name": item["name"],
                "path": item["path"],
                "github_url": item.get("github_url"),
                "excerpt": item["excerpt"],
                "score": score,
            }
        )

    if not selected:
        for _, _, item in ranked[:REPORTS_CONTEXT_LIMIT]:
            selected.append(
                {
                    "name": item["name"],
                    "path": item["path"],
                    "github_url": item.get("github_url"),
                    "excerpt": item["excerpt"],
                    "score": 0,
                }
            )

    index = [
        {
            "name": item["name"],
            "path": item["path"],
            "github_url": item.get("github_url"),
        }
        for item in catalog[:REPORTS_INDEX_LIMIT]
    ]

    return {
        "reports_available": len(catalog),
        "reports_directory": "reports/",
        "reports_index": index,
        "relevant_reports": selected,
    }


def build_fasting_context(data: dict) -> dict:
    fast = data.get("fast", {}) or {}
    measurements = sorted(data.get("measurements", []) or [], key=lambda m: m.get("date", ""))
    latest = measurements[-1] if measurements else {}
    start_str = (fast.get("start") or "").split("T")[0]
    today = datetime.now().date()

    current_day = latest.get("day") if isinstance(latest, dict) else None
    if not isinstance(current_day, int):
        try:
            start_date = datetime.strptime(start_str, "%Y-%m-%d").date()
            current_day = max(1, (today - start_date).days + 1)
        except Exception:
            current_day = 1

    recent_days = []
    for measurement in measurements[-10:]:
        oura = measurement.get("oura", {}) or {}
        recent_days.append(
            {
                "date": measurement.get("date"),
                "day": measurement.get("day"),
                "weight_kg": measurement.get("weight_kg"),
                "water_liters": measurement.get("water_liters"),
                "sleep_score": oura.get("sleep_score"),
                "readiness_score": oura.get("readiness_score"),
                "total_calories": oura.get("total_calories"),
                "steps": oura.get("steps"),
            }
        )

    return {
        "cycle": data.get("cycle"),
        "current_day": current_day,
        "profile": data.get("profile", {}),
        "fast": {
            "start": fast.get("start"),
            "end": fast.get("end"),
            "goal_days": fast.get("goal_days"),
        },
        "baseline": data.get("baseline", {}),
        "latest_measurement": latest,
        "recent_measurements": recent_days,
    }


def resolve_minimax_api_key() -> str:
    env_key = (
        os.environ.get("MINIMAX_API_KEY")
        or os.environ.get("KIMI_API_KEY")
        or os.environ.get("MOONSHOT_API_KEY")
        or ""
    ).strip()
    if env_key:
        return env_key

    for token_file in (
        ROOT_DIR / ".minimax_token",
        ROOT_DIR / ".minimax_key",
        ROOT_DIR / ".kimi_token",
        ROOT_DIR / ".kimi_key",
    ):
        if token_file.exists():
            key = token_file.read_text(encoding="utf-8").strip()
            if key:
                return key
    return ""


def minimax_base_url() -> str:
    return (os.environ.get("MINIMAX_BASE_URL") or os.environ.get("KIMI_BASE_URL") or DEFAULT_MINIMAX_BASE_URL).rstrip("/")


def minimax_alternate_base_url(base_url: str) -> str | None:
    if base_url.startswith("https://api.minimax.io/"):
        return base_url.replace("https://api.minimax.io/", "https://api.minimaxi.com/", 1)
    if base_url.startswith("https://api.minimaxi.com/"):
        return base_url.replace("https://api.minimaxi.com/", "https://api.minimax.io/", 1)
    return None


def minimax_base_url_candidates() -> list[str]:
    configured = (os.environ.get("MINIMAX_BASE_URL") or os.environ.get("KIMI_BASE_URL") or "").strip()
    base = minimax_base_url()
    if configured:
        return [base]
    alt = minimax_alternate_base_url(base)
    if alt and alt != base:
        return [base, alt]
    return [base]


def minimax_model() -> str:
    return (os.environ.get("MINIMAX_MODEL") or os.environ.get("KIMI_MODEL") or DEFAULT_MINIMAX_MODEL).strip()


def minimax_ssl_context() -> ssl.SSLContext | None:
    if os.environ.get("MINIMAX_INSECURE_SKIP_VERIFY", "").strip().lower() in ("1", "true", "yes", "on"):
        return ssl._create_unverified_context()

    ca_file = (os.environ.get("MINIMAX_CA_FILE") or "").strip()
    if ca_file:
        return ssl.create_default_context(cafile=ca_file)

    return None


def format_minimax_message_content(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
        return "\n".join(chunks).strip()
    return ""


def strip_internal_think_blocks(text: str) -> str:
    cleaned = THINK_BLOCK_RE.sub("", text).strip()
    return cleaned or text.strip()


def call_minimax(chat_messages: list[dict], fasting_context: dict, reports_context: dict) -> str:
    api_key = resolve_minimax_api_key()
    if not api_key:
        raise RuntimeError(
            "MiniMax API key is not set. Set MINIMAX_API_KEY or create .minimax_token in this folder."
        )

    prompt_messages: list[dict] = [
        {
            "role": "system",
            "content": (
                "You are a practical fasting coach assistant for one user. "
                "Use their tracker context and conversation memory. "
                "Be concise, specific, and action-oriented. "
                "For medical-risk questions, include a safety warning and advise professional care."
            ),
        },
        {
            "role": "system",
            "content": "Tracker context (JSON):\n" + json.dumps(fasting_context, ensure_ascii=False),
        },
        {
            "role": "system",
            "content": (
                "Reports knowledge base from GitHub-cloned repository (JSON). "
                "Use relevant reports when helpful and cite report filenames in answers.\n"
                + json.dumps(reports_context, ensure_ascii=False)
            ),
        },
    ]
    prompt_messages.extend(chat_messages[-CHAT_CONTEXT_MESSAGES:])

    payload = {
        "model": minimax_model(),
        "temperature": 0.4,
        "messages": prompt_messages,
    }
    body = json.dumps(payload).encode("utf-8")
    ssl_context = minimax_ssl_context()
    urls = minimax_base_url_candidates()
    raw = ""
    last_error: RuntimeError | None = None

    for idx, base_url in enumerate(urls):
        request = Request(
            f"{base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=60, context=ssl_context) as response:
                raw = response.read().decode("utf-8")
                last_error = None
                break
        except HTTPError as e:
            details = ""
            try:
                details = e.read().decode("utf-8")
            except Exception:
                details = str(e)

            if (
                idx < len(urls) - 1
                and e.code == 401
                and ("invalid api key" in details.lower() or "authorized_error" in details.lower())
            ):
                continue
            last_error = RuntimeError(f"MiniMax API error ({e.code}): {details[:300]}")
            break
        except URLError as e:
            last_error = RuntimeError(f"Could not reach MiniMax API: {e.reason}")
            break

    if last_error is not None:
        raise last_error

    try:
        parsed = json.loads(raw)
        content = parsed["choices"][0]["message"]["content"]
        text = format_minimax_message_content(content)
        if not text:
            raise RuntimeError("MiniMax returned an empty response.")
        return strip_internal_think_blocks(text)
    except Exception as e:
        raise RuntimeError(f"Unexpected MiniMax response: {raw[:300]}") from e


def get_chat_history(limit: int = 200) -> list[dict]:
    with CHAT_LOCK:
        payload = read_chat_memory_unlocked()
        messages = normalize_chat_messages(payload.get("messages", []))
        payload["messages"] = messages
        payload["updated_at"] = now_iso()
        write_chat_memory_unlocked(payload)
    return messages[-max(1, min(limit, CHAT_HISTORY_LIMIT)) :]


def clear_chat_history() -> None:
    with CHAT_LOCK:
        payload = {"messages": [], "updated_at": now_iso()}
        write_chat_memory_unlocked(payload)


def process_chat_message(user_text: str) -> dict:
    user_text = (user_text or "").strip()
    if not user_text:
        raise ValueError("message is required")
    if len(user_text) > 4000:
        raise ValueError("message is too long (max 4000 characters)")

    data_snapshot = read_data_snapshot()
    fasting_context = build_fasting_context(data_snapshot)

    user_message = {"role": "user", "content": user_text, "timestamp": now_iso()}
    with CHAT_LOCK:
        memory = read_chat_memory_unlocked()
        messages = normalize_chat_messages(memory.get("messages", []))
        messages.append(user_message)
        messages = messages[-CHAT_HISTORY_LIMIT:]
        memory["messages"] = messages
        memory["updated_at"] = now_iso()
        write_chat_memory_unlocked(memory)
        prompt_messages = [{"role": m["role"], "content": m["content"]} for m in messages]

    reports_context = reports_context_for_query(user_text, prompt_messages)
    assistant_text = call_minimax(prompt_messages, fasting_context, reports_context)
    assistant_message = {"role": "assistant", "content": assistant_text, "timestamp": now_iso()}

    with CHAT_LOCK:
        memory = read_chat_memory_unlocked()
        messages = normalize_chat_messages(memory.get("messages", []))
        messages.append(assistant_message)
        memory["messages"] = messages[-CHAT_HISTORY_LIMIT:]
        memory["updated_at"] = now_iso()
        write_chat_memory_unlocked(memory)

    return {
        "ok": True,
        "assistant": assistant_message,
        "configured": bool(resolve_minimax_api_key()),
        "model": minimax_model(),
    }


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT_DIR), **kwargs)

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "86400")

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._send_cors_headers()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def do_OPTIONS(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.send_response(204)
            self._send_cors_headers()
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/data":
                snapshot = read_data_snapshot()
                self._send_json(200, {"ok": True, "data": snapshot})
                return
            if path == "/api/health":
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "storage": "sqlite",
                        "db_file": DB_FILE.name,
                        "chat_configured": bool(resolve_minimax_api_key()),
                        "chat_model": minimax_model(),
                        "reports_available": len(load_reports_catalog()),
                        "auto_sync": auto_sync_state_payload(),
                    },
                )
                return
            if path == "/api/chat/history":
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "configured": bool(resolve_minimax_api_key()),
                        "model": minimax_model(),
                        "messages": get_chat_history(),
                    },
                )
                return
            if path == "/api/sync/status":
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "latest": latest_sync_run("oura"),
                        "auto_sync": auto_sync_state_payload(),
                    },
                )
                return
            super().do_GET()
        except Exception:
            if path.startswith("/api/"):
                self._send_json(500, {"ok": False, "error": "Internal error"})
            else:
                self.send_error(500, "Internal error")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/checkin":
            try:
                payload = self._read_json_body()
                result = upsert_checkin(payload)
                self._send_json(200, result)
            except ValueError as e:
                self._send_json(400, {"ok": False, "error": str(e)})
            except Exception:
                self._send_json(500, {"ok": False, "error": "Internal error"})
            return

        if path == "/api/profile":
            try:
                payload = self._read_json_body()
                result = upsert_profile(payload)
                self._send_json(200, result)
            except ValueError as e:
                self._send_json(400, {"ok": False, "error": str(e)})
            except Exception:
                self._send_json(500, {"ok": False, "error": "Internal error"})
            return

        if path == "/api/sync/oura":
            try:
                payload = self._read_json_body()
                result = sync_oura_data(
                    start_date=payload.get("start_date") if isinstance(payload, dict) else None,
                    end_date=payload.get("end_date") if isinstance(payload, dict) else None,
                    token_override=payload.get("token") if isinstance(payload, dict) else None,
                    source="manual",
                )
                self._send_json(200, result)
            except ValueError as e:
                self._send_json(400, {"ok": False, "error": str(e)})
            except RuntimeError as e:
                self._send_json(503, {"ok": False, "error": str(e)})
            except Exception:
                self._send_json(500, {"ok": False, "error": "Internal error"})
            return

        if path == "/api/chat":
            try:
                payload = self._read_json_body()
                message = payload.get("message", "")
                result = process_chat_message(message)
                self._send_json(200, result)
            except ValueError as e:
                self._send_json(400, {"ok": False, "error": str(e)})
            except RuntimeError as e:
                self._send_json(503, {"ok": False, "error": str(e)})
            except Exception:
                self._send_json(500, {"ok": False, "error": "Internal error"})
            return

        if path == "/api/chat/clear":
            clear_chat_history()
            self._send_json(200, {"ok": True})
            return

        self._send_json(404, {"ok": False, "error": "Not found"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    ensure_storage_ready()
    start_auto_sync_thread()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), AppHandler)
    print(f"Fasting Tracker server running at http://127.0.0.1:{args.port}/index.html")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        AUTO_SYNC_STOP_EVENT.set()
        server.server_close()


if __name__ == "__main__":
    main()
