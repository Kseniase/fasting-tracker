#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def http_json(base: str, path: str, method: str = "GET", payload: dict | None = None, timeout: float = 15.0):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(f"{base}{path}", data=data, method=method, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body)
    except HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        parsed = {}
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {"raw": body}
        return e.code, parsed
    except URLError as e:
        raise RuntimeError(f"Network error for {path}: {e.reason}") from e


def wait_for_health(base: str, timeout_s: float = 12.0):
    deadline = time.time() + timeout_s
    last_err = None
    while time.time() < deadline:
        try:
            status, payload = http_json(base, "/api/health")
            if status == 200 and payload.get("ok"):
                return payload
        except Exception as e:
            last_err = e
        time.sleep(0.15)
    raise RuntimeError(f"Server did not become healthy at {base}. Last error: {last_err}")


def latest_non_future_date(measurements: list[dict]) -> str:
    valid = [m for m in measurements if isinstance(m, dict) and isinstance(m.get("date"), str)]
    if not valid:
        raise RuntimeError("No measurements found to use for fuzz tests")
    valid.sort(key=lambda m: m["date"])
    return valid[-1]["date"]


def run_fuzz(base: str):
    failures: list[str] = []

    status, health = http_json(base, "/api/health")
    if status != 200 or health.get("storage") != "sqlite":
        failures.append(f"health/storage check failed: status={status}, payload={health}")

    status, data_resp = http_json(base, "/api/data")
    if status != 200 or not data_resp.get("ok"):
        failures.append(f"/api/data failed: {status} {data_resp}")
        return failures

    measurements = data_resp.get("data", {}).get("measurements", [])
    target_date = latest_non_future_date(measurements)
    target = next((m for m in measurements if m.get("date") == target_date), None)
    if not target:
        failures.append("target measurement not found")
        return failures

    original_weight = target.get("weight_kg")
    original_water = target.get("water_liters")

    def restore_original():
        restore_payload = {
            "date": target_date,
            "weight_kg": original_weight,
            "water_liters": original_water,
        }
        http_json(base, "/api/checkin", method="POST", payload=restore_payload)

    try:
        invalid_cases = [
            ({}, 400),
            ({"date": "2026/02/24", "weight_kg": 70}, 400),
            ({"date": "2026-13-40", "weight_kg": 70}, 400),
            ({"date": target_date, "weight_kg": 10}, 400),
            ({"date": target_date, "weight_kg": 999}, 400),
            ({"date": target_date, "water_liters": -1}, 400),
            ({"date": target_date, "water_liters": 99}, 400),
        ]
        for payload, expected in invalid_cases:
            status, _ = http_json(base, "/api/checkin", method="POST", payload=payload)
            if status != expected:
                failures.append(f"invalid payload should return {expected}, got {status}: {payload}")

        # Baseline known state.
        status, _ = http_json(
            base,
            "/api/checkin",
            method="POST",
            payload={"date": target_date, "weight_kg": 70.0, "water_liters": 2.0},
        )
        if status != 200:
            failures.append(f"failed baseline set for target date {target_date}")

        # Partial update: weight only should preserve water.
        status, _ = http_json(
            base,
            "/api/checkin",
            method="POST",
            payload={"date": target_date, "weight_kg": 70.4},
        )
        if status != 200:
            failures.append("weight-only partial update failed")

        status, data_resp = http_json(base, "/api/data")
        m = next((x for x in data_resp.get("data", {}).get("measurements", []) if x.get("date") == target_date), None)
        if not m:
            failures.append("target measurement missing after partial update")
        else:
            if m.get("weight_kg") != 70.4:
                failures.append(f"weight-only partial update mismatch: {m.get('weight_kg')}")
            if m.get("water_liters") != 2.0:
                failures.append(f"water should remain 2.0 after weight-only update, got {m.get('water_liters')}")

        # Omitted fields should not clear existing values.
        status, payload = http_json(base, "/api/checkin", method="POST", payload={"date": target_date})
        if status != 200:
            failures.append("empty PATCH-like payload failed")
        else:
            if payload.get("weight_kg") != 70.4 or payload.get("water_liters") != 2.0:
                failures.append(f"empty payload changed values unexpectedly: {payload}")

        # Concurrency stress on same date.
        updates = []
        for _ in range(24):
            w = round(random.uniform(65.0, 75.0), 1)
            water = round(random.uniform(1.0, 4.0), 1)
            updates.append((w, water))

        lock = threading.Lock()
        statuses: list[int] = []

        def worker(item):
            w, water = item
            s, _ = http_json(
                base,
                "/api/checkin",
                method="POST",
                payload={"date": target_date, "weight_kg": w, "water_liters": water},
            )
            with lock:
                statuses.append(s)

        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(worker, updates))

        if any(s != 200 for s in statuses):
            failures.append(f"concurrency updates had non-200 statuses: {statuses}")

        status, data_resp = http_json(base, "/api/data")
        m = next((x for x in data_resp.get("data", {}).get("measurements", []) if x.get("date") == target_date), None)
        if not m:
            failures.append("target measurement missing after concurrency test")
        else:
            w = m.get("weight_kg")
            water = m.get("water_liters")
            if w is None or not (65.0 <= float(w) <= 75.0):
                failures.append(f"final weight out of expected range after concurrency: {w}")
            if water is None or not (1.0 <= float(water) <= 4.0):
                failures.append(f"final water out of expected range after concurrency: {water}")

        # Validate clear semantics explicit null only.
        status, payload = http_json(
            base,
            "/api/checkin",
            method="POST",
            payload={"date": target_date, "weight_kg": None, "water_liters": None},
        )
        if status != 200:
            failures.append("explicit clear failed")
        elif payload.get("weight_kg") is not None or payload.get("water_liters") is not None:
            failures.append(f"explicit clear did not clear: {payload}")

        # Profile endpoint validation.
        status, _ = http_json(base, "/api/profile", method="POST", payload={"height_cm": 50})
        if status != 400:
            failures.append(f"profile validation failed, expected 400 got {status}")

        status, _ = http_json(base, "/api/profile", method="POST", payload={"height_cm": 174})
        if status != 200:
            failures.append("profile valid update failed")

        # Sync status endpoint shape.
        status, sync_payload = http_json(base, "/api/sync/status")
        if status != 200 or not sync_payload.get("ok"):
            failures.append(f"sync status endpoint failed: {status} {sync_payload}")

        # Sync endpoint should fail cleanly with invalid token (503, not 500).
        status, sync_run_payload = http_json(
            base,
            "/api/sync/oura",
            method="POST",
            payload={"start_date": target_date, "end_date": target_date, "token": "invalid-token-for-fuzz-test"},
        )
        if status != 503:
            failures.append(f"sync invalid-token should return 503, got {status}: {sync_run_payload}")

        # Chat history endpoint should be healthy (non-destructive, no message send).
        status, chat_hist = http_json(base, "/api/chat/history")
        if status != 200 or not chat_hist.get("ok"):
            failures.append(f"chat history endpoint failed: {status} {chat_hist}")

    finally:
        restore_original()

    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8101)
    args = parser.parse_args()

    env = os.environ.copy()
    env["OURA_AUTO_SYNC"] = "0"

    proc = subprocess.Popen(
        ["python3", "app_server.py", "--port", str(args.port)],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )

    try:
        base = f"http://127.0.0.1:{args.port}"
        wait_for_health(base)
        failures = run_fuzz(base)
        if failures:
            print("API fuzz failed:")
            for item in failures:
                print(f"- {item}")
            return 1
        print("API fuzz passed.")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=4)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


if __name__ == "__main__":
    sys.exit(main())
