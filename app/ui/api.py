"""Small, explicit Python API exposed to the local WebView dashboard."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any

from app.settings.presets import apply_preset
from app.settings.schema import merge_vision_settings
from app.settings.storage import (
    load_vision_settings,
    public_settings_view,
    reset_vision_settings,
    save_vision_settings,
)
from app.ui.controller import ProtectionStatus
from app.ui.rules import RuleConflict, RuleEditor
from app.vision.model_lifecycle import (
    inspect_models,
    start_download,
    start_download_all,
)
from app.vision.settings import vision_settings_snapshot


class DashboardAPI:
    """Expose only control and privacy-safe read operations to JavaScript."""

    def __init__(
        self, controller, recorder, diagnostics=None, rule_store=None, app_picker=None,
        data_dir=None,
    ) -> None:
        self.controller = controller
        self.recorder = recorder
        self.diagnostics = controller if diagnostics is None else diagnostics
        self.rule_editor = None if rule_store is None else RuleEditor(rule_store)
        self.app_picker = app_picker
        self._data_dir = None if data_dir is None else Path(data_dir)
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
            settings = load_vision_settings(self._data_dir)
            snapshot = vision_settings_snapshot(settings)
            snapshot.update(public_settings_view(settings))
            return {"ok": True, "settings": snapshot}
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not read vision settings", error)

    def save_vision_settings(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            current = load_vision_settings(self._data_dir)
            merged = merge_vision_settings(current, payload or {})
            if self._data_dir is not None:
                save_vision_settings(merged, self._data_dir)
            restarted = self._safe_restart_protection()
            snapshot = vision_settings_snapshot(merged)
            snapshot.update(public_settings_view(merged))
            return {
                "ok": True,
                "settings": snapshot,
                "restarted": restarted,
                "message": (
                    "Settings saved. Protection was restarted to apply the models."
                    if restarted
                    else "Settings saved. They apply the next time protection starts."
                ),
            }
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not save vision settings", error)

    def apply_vision_preset(self, name: str) -> dict[str, Any]:
        try:
            current = load_vision_settings(self._data_dir)
            merged = apply_preset(str(name), current)
            if self._data_dir is not None:
                save_vision_settings(merged, self._data_dir)
            restarted = self._safe_restart_protection()
            snapshot = vision_settings_snapshot(merged)
            snapshot.update(public_settings_view(merged))
            return {
                "ok": True,
                "settings": snapshot,
                "restarted": restarted,
                "message": "Preset applied. Values remain experimental until benchmarked.",
            }
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not apply detection preset", error)

    def reset_vision_settings(self) -> dict[str, Any]:
        try:
            if self._data_dir is not None:
                settings = reset_vision_settings(self._data_dir)
            else:
                from app.settings.schema import sanitize_vision_settings

                settings = sanitize_vision_settings(None)
            restarted = self._safe_restart_protection()
            snapshot = vision_settings_snapshot(settings)
            snapshot.update(public_settings_view(settings))
            return {
                "ok": True,
                "settings": snapshot,
                "restarted": restarted,
                "message": "Experimental defaults restored.",
            }
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not reset vision settings", error)

    def get_model_status(self) -> dict[str, Any]:
        try:
            models = inspect_models(data_dir=self._data_dir)
            return {"ok": True, "models": models}
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not read model status", error)

    def download_model(self, model_id: str) -> dict[str, Any]:
        try:
            row = start_download(str(model_id), data_dir=self._data_dir)
            return {
                "ok": True,
                "model": row,
                "message": (
                    f"{row['label']} download started."
                    if row.get("status") == "downloading"
                    else f"{row['label']} status: {row.get('status')}."
                ),
            }
        except ValueError:
            return {"ok": False, "message": "Unknown model."}
        except RuntimeError as error:
            return {"ok": False, "message": str(error)}
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not start model download", error)

    def download_all_models(self) -> dict[str, Any]:
        try:
            models = start_download_all(data_dir=self._data_dir)
            return {
                "ok": True,
                "models": models,
                "message": "Required model downloads started.",
            }
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not start model downloads", error)

    def download_optional_model(self, model_id: str) -> dict[str, Any]:
        return self.download_model(model_id)

    def _safe_restart_protection(self) -> bool:
        status = getattr(self.controller, "status", None)
        from app.ui.controller import ProtectionStatus as _Status

        running = status is _Status.RUNNING if status is not None else False
        if not running:
            return False
        restart = getattr(self.controller, "restart", None)
        return bool(restart()) if callable(restart) else False

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
