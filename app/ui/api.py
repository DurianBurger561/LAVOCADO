"""Small, explicit Python API exposed to the local WebView dashboard."""

from __future__ import annotations

from datetime import datetime
from threading import RLock
from typing import Any

from app.ui.controller import ProtectionStatus
from app.ui.rules import RuleConflict, RuleEditor
from app.vision.settings import vision_settings_snapshot


class DashboardAPI:
    """Expose only control and privacy-safe read operations to JavaScript."""

    def __init__(
        self, controller, recorder, diagnostics=None, rule_store=None, app_picker=None
    ) -> None:
        self.controller = controller
        self.recorder = recorder
        self.diagnostics = controller if diagnostics is None else diagnostics
        self.rule_editor = None if rule_store is None else RuleEditor(rule_store)
        self.app_picker = app_picker
        self._rule_lock = RLock()

    def start_protection(self) -> dict[str, Any]:
        try:
            with self._rule_lock:
                started = self.controller.start()
            return self._action_result(
                started,
                "Protection started.",
                "Protection is already active.",
            )
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not start protection", error)

    def stop_protection(self) -> dict[str, Any]:
        try:
            stopped = self.controller.stop()
            return self._action_result(
                stopped,
                "Protection is stopping safely.",
                "Protection is not running.",
            )
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not stop protection", error)

    def get_status(self) -> dict[str, Any]:
        try:
            status = self.controller.status
            return {
                "ok": True,
                "status": status.value,
                "exit_code": self.controller.last_exit_code,
                "can_start": status in (ProtectionStatus.STOPPED, ProtectionStatus.FAILED),
                "can_stop": status is ProtectionStatus.RUNNING,
            }
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not read protection status", error)

    def get_events(self, limit: int = 50) -> dict[str, Any]:
        try:
            safe_limit = min(100, max(1, int(limit)))
            events = [self._event_to_dict(event) for event in self.recorder.recent(safe_limit)]
            return {
                "ok": True,
                "total": int(self.recorder.count()),
                "events": events,
            }
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not read local history", error)

    def get_diagnostics(self) -> dict[str, Any]:
        try:
            return {"ok": True, "diagnostics": self.diagnostics.snapshot()}
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not read diagnostics", error)

    def get_vision_settings(self) -> dict[str, Any]:
        try:
            return {"ok": True, "settings": vision_settings_snapshot()}
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not read vision settings", error)

    def test_intervention(self) -> dict[str, Any]:
        try:
            requested = self.controller.test_intervention()
            return self._action_result(
                requested,
                "Test intervention requested.",
                "Start protection before testing the intervention.",
            )
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not test intervention", error)

    def get_rules(self) -> dict[str, Any]:
        try:
            with self._rule_lock:
                editor = self._require_rule_editor()
                rules = editor.snapshot()
                can_edit = self._can_edit_rules()
            return {"ok": True, "rules": rules, "can_edit": can_edit}
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not read protection rules", error)

    def add_rule(
        self,
        group: str,
        value: str,
        match_mode: str = "exact_host",
        replace_conflict: bool = False,
    ) -> dict[str, Any]:
        try:
            with self._rule_lock:
                editor = self._require_rule_editor()
                if not self._can_edit_rules():
                    return self._rules_running_result()
                if not isinstance(replace_conflict, bool):
                    raise TypeError("Invalid replacement choice.")
                editor.add(group, value, match_mode, replace_conflict)
                rules = editor.snapshot()
            return {"ok": True, "rules": rules, "can_edit": True,
                    "message": "Rule saved. It will apply when protection starts."}
        except RuleConflict as error:
            return {"ok": False, "conflict": True, "message": str(error)}
        except (TypeError, ValueError):
            return {"ok": False, "message": "Invalid rule value or match mode."}
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not save protection rule", error)

    def remove_rule(
        self, group: str, value: str, match_mode: str = "exact_host"
    ) -> dict[str, Any]:
        try:
            with self._rule_lock:
                editor = self._require_rule_editor()
                if not self._can_edit_rules():
                    return self._rules_running_result()
                changed = editor.remove(group, value, match_mode)
                rules = editor.snapshot()
            return {"ok": True, "rules": rules, "can_edit": True, "changed": changed,
                    "message": "Rule removed. Changes apply when protection starts."}
        except (TypeError, ValueError):
            return {"ok": False, "message": "Invalid rule value or match mode."}
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not remove protection rule", error)

    def begin_app_pick(self) -> dict[str, Any]:
        try:
            with self._rule_lock:
                if not self._can_edit_rules():
                    return self._rules_running_result()
                if self.app_picker is None:
                    raise RuntimeError("Application selection is unavailable")
                return {"ok": True, **self.app_picker.begin()}
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not select an application", error)

    def get_app_pick_result(self) -> dict[str, Any]:
        try:
            if self.app_picker is None:
                raise RuntimeError("Application selection is unavailable")
            return {"ok": True, **self.app_picker.result()}
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not read application selection", error)

    def _require_rule_editor(self) -> RuleEditor:
        if self.rule_editor is None:
            raise RuntimeError("Rule storage is unavailable")
        return self.rule_editor

    def _can_edit_rules(self) -> bool:
        return self.controller.status in (ProtectionStatus.STOPPED, ProtectionStatus.FAILED)

    @staticmethod
    def _rules_running_result() -> dict[str, Any]:
        return {"ok": False, "can_edit": False,
                "message": "Stop protection before editing rules."}

    def _action_result(
        self,
        changed: bool,
        success_message: str,
        unchanged_message: str,
    ) -> dict[str, Any]:
        result = self.get_status()
        result["changed"] = bool(changed)
        result["message"] = success_message if changed else unchanged_message
        return result

    @staticmethod
    def _event_to_dict(event) -> dict[str, Any]:
        occurred_at = datetime.fromisoformat(event.occurred_at)
        if occurred_at.tzinfo is not None:
            occurred_at = occurred_at.astimezone()
        return {
            "id": int(event.id),
            "occurred_at": occurred_at.isoformat(timespec="seconds"),
            "trigger_type": str(event.trigger_type),
            "label": None if event.label is None else str(event.label),
            "confidence": (
                None if event.confidence is None else float(event.confidence)
            ),
            "monitor_index": int(event.monitor_index),
            "intervention_shown": bool(event.intervention_shown),
        }

    @staticmethod
    def _error_result(message: str, error: Exception) -> dict[str, Any]:
        return {
            "ok": False,
            "message": f"{message}: {type(error).__name__}",
        }
