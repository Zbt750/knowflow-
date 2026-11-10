from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


ALLOWED_TYPES = set("ABCDEF")
PASS_VALUES = {"PASS", "PASS_WITH_EVIDENCE"}


def check(audit: Path) -> list[str]:
    errors: list[str] = []
    scenarios_path = audit / "REAL-USER-SCENARIOS.json"
    for required in ("SCREENSHOT-INDEX.md", "REAL-USER-INTERACTION-REPORT.md", "REAL-USER-SCENARIOS.json"):
        if not (audit / required).is_file():
            errors.append(f"missing required file: {required}")
    if errors or not scenarios_path.exists():
        return errors
    try:
        data = json.loads(scenarios_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"invalid REAL-USER-SCENARIOS.json: {type(exc).__name__}: {exc}"]
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        return ["scenarios must be a non-empty array"]
    seen: set[str] = set()
    for index, scenario in enumerate(scenarios):
        label = f"scenario[{index}]"
        sid = scenario.get("test_id")
        if not isinstance(sid, str) or not sid:
            errors.append(f"{label}: missing test_id")
            continue
        if sid in seen:
            errors.append(f"{sid}: duplicate test_id")
        seen.add(sid)
        status = scenario.get("result")
        if status not in {"PASS", "PARTIAL", "FAIL", "NOT_TESTED", "BLOCKED"}:
            errors.append(f"{sid}: invalid result {status!r}")
        kinds = scenario.get("evidence_types")
        if not isinstance(kinds, list) or not kinds or any(kind not in ALLOWED_TYPES for kind in kinds):
            errors.append(f"{sid}: evidence_types must contain A-F labels")
            kinds = []
        turns = scenario.get("turns")
        if status != "NOT_TESTED":
            if not isinstance(turns, list) or not turns:
                errors.append(f"{sid}: executed scenario has no turns")
            else:
                for turn_index, turn in enumerate(turns):
                    if not turn.get("user_input"):
                        errors.append(f"{sid}: turn[{turn_index}] has no actual user_input")
                    if not turn.get("assistant_reply"):
                        errors.append(f"{sid}: turn[{turn_index}] has no actual assistant_reply")
                    if not turn.get("next_user_action") and turn_index < len(turns) - 1:
                        errors.append(f"{sid}: turn[{turn_index}] has no next_user_action")
        if status in PASS_VALUES:
            if "A" not in kinds:
                errors.append(f"{sid}: PASS requires A real-browser/backend/isolated-database evidence")
            evidence = scenario.get("business_evidence") or {}
            if not evidence.get("api_or_database_readback"):
                errors.append(f"{sid}: PASS has no API/database readback reference")
            if not evidence.get("actual_outcome"):
                errors.append(f"{sid}: PASS has no actual business outcome")
            if scenario.get("category") == "personal-ai" and (
                "F" not in kinds or not evidence.get("live_provider_call") or not evidence.get("saved_personal_question_readback")
            ):
                errors.append(f"{sid}: personal-ai PASS requires F live-provider and saved-question readback")
        screenshot_paths = scenario.get("screenshots")
        if not isinstance(screenshot_paths, list) or not screenshot_paths:
            errors.append(f"{sid}: no screenshots linked")
            screenshot_paths = []
        for rel in screenshot_paths:
            screenshot = (audit / rel).resolve()
            if audit.resolve() not in screenshot.parents:
                errors.append(f"{sid}: screenshot path escapes audit directory: {rel}")
                continue
            if sid not in screenshot.name:
                errors.append(f"{sid}: screenshot name does not include test id: {rel}")
            if not screenshot.is_file():
                errors.append(f"{sid}: missing screenshot: {rel}")
                continue
            try:
                raw = screenshot.read_bytes()
                if len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n":
                    errors.append(f"{sid}: invalid or non-PNG screenshot: {rel}")
                    continue
                width, height = struct.unpack(">II", raw[16:24])
                if width < 300 or height < 200:
                    errors.append(f"{sid}: implausible screenshot dimensions {width}x{height}: {rel}")
            except OSError as exc:
                errors.append(f"{sid}: cannot read screenshot {rel}: {exc}")
        responsive = scenario.get("responsive_widths") or []
        if scenario.get("responsive_required"):
            for width in (1440, 430, 390, 360):
                if width not in responsive:
                    errors.append(f"{sid}: required viewport {width}px not recorded")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate NAIWA real-user acceptance evidence linkage.")
    parser.add_argument("audit_dir", type=Path)
    args = parser.parse_args()
    errors = check(args.audit_dir.resolve())
    if errors:
        print("\n".join(f"FAIL: {item}" for item in errors))
        return 1
    print(f"PASS: screenshot and real-user evidence links are consistent in {args.audit_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
