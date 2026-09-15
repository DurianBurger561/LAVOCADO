"""Small, explicit Python API exposed to the local WebView dashboard."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from threading import Lock, RLock
from typing import Any

from app.intervention.llm import DEFAULT_ENDPOINT, DEFAULT_MODEL, LLMClient, LLMUnavailable, resolve_language
from app.intervention.llm_settings import LLMSettings, load_llm_settings, save_llm_settings
from app.intervention.llm_status import LLMStatus
from app.settings.presets import apply_preset
from app.settings.schema import merge_vision_settings
from app.settings.storage import (
    load_vision_settings,
    public_settings_view,
    reset_vision_settings,
    save_vision_settings,
)
from app.ui.controller import ProtectionStatus
from app.ui.language import SUPPORTED_LANGUAGES, load_ui_language, save_ui_language
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
        self._ui_language = load_ui_language(self._data_dir)
        self._rule_lock = RLock()
        self._llm_test_lock = Lock()
        self._llm_probe = None

    def get_ui_language(self) -> dict[str, Any]:
        return {"ok": True, "language": self._ui_language}

    def set_ui_language(self, language: str) -> dict[str, Any]:
        if not isinstance(language, str) or language not in SUPPORTED_LANGUAGES:
            return {"ok": False, "message": "Unsupported dashboard language."}
        try:
            self._ui_language = save_ui_language(self._data_dir, language)
        except OSError as error:
            return self._error_result("Could not save dashboard language", error)
        return {"ok": True, "language": self._ui_language}

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

    def get_llm_settings(self) -> dict[str, Any]:
        """Return connection metadata without ever returning the API key."""

        try:
            stored = load_llm_settings(self._data_dir)
            environment_key = (
                os.environ.get("LAVOCADO_LLM_API_KEY")
                or os.environ.get("OPENAI_API_KEY")
                or os.environ.get("DEEPSEEK_API_KEY")
                or ""
            )
            environment_endpoint = (
                os.environ.get("LAVOCADO_LLM_ENDPOINT")
                or os.environ.get("OPENAI_BASE_URL")
                or os.environ.get("DEEPSEEK_BASE_URL")
                or ""
            )
            environment_model = (
                os.environ.get("LAVOCADO_LLM_MODEL")
                or os.environ.get("OPENAI_MODEL")
                or os.environ.get("DEEPSEEK_MODEL")
                or ""
            )
            client = LLMClient(
                api_key=(stored.api_key or environment_key) if stored.enabled else "",
                endpoint=stored.endpoint or environment_endpoint or DEFAULT_ENDPOINT,
                model=stored.model or environment_model or DEFAULT_MODEL,
            )
            status = LLMStatus("unverified" if client.configured else "unconfigured")
            checked_at = ""
            probe = self._llm_probe
            if probe is not None and probe[0] == self._llm_signature(client):
                status, checked_at = probe[1:]
            return {
                "ok": True,
                "enabled": stored.enabled,
                "endpoint": stored.endpoint or environment_endpoint or DEFAULT_ENDPOINT,
                "model": stored.model or environment_model or DEFAULT_MODEL,
                "language": stored.language,
                "language_in_use": resolve_language(stored.language, self._data_dir),
                "api_key_set": bool(stored.api_key or environment_key) and stored.enabled,
                "connection": {**status.public_view(self._ui_language), "checked_at": checked_at},
                "api_key_source": (
                    "dashboard" if stored.api_key
                    else "environment" if environment_key
                    else "none"
                ),
            }
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not read AI settings", error)

    def save_llm_settings(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Persist optional LLM connection details and keep the key write-only in the UI."""

        try:
            if self._data_dir is None:
                raise RuntimeError("LLM settings storage is unavailable.")
            current = load_llm_settings(self._data_dir)
            values = payload if isinstance(payload, dict) else {}
            api_key = values.get("api_key")
            if isinstance(api_key, str) and api_key.strip():
                next_key = api_key.strip()
            elif values.get("clear_api_key") is True:
                next_key = ""
            else:
                next_key = current.api_key
            endpoint = values.get("endpoint", current.endpoint)
            model = values.get("model", current.model)
            enabled = values.get("enabled", current.enabled)
            language = values.get("language", current.language)
            settings = LLMSettings(
                api_key=next_key if isinstance(next_key, str) else current.api_key,
                endpoint=endpoint.strip() if isinstance(endpoint, str) else current.endpoint,
                model=model.strip() if isinstance(model, str) else current.model,
                enabled=enabled if isinstance(enabled, bool) else current.enabled,
                language=language if isinstance(language, str) else current.language,
            )
            save_llm_settings(settings, self._data_dir)
            self._llm_probe = None
            result = self.get_llm_settings()
            if result.get("ok"):
                result["message"] = "AI settings saved. They apply to the next intervention."
            return result
        except Exception as error:  # noqa: BLE001 - JSON API boundary
            return self._error_result("Could not save AI settings", error)

    @staticmethod
    def _llm_signature(client: LLMClient) -> tuple[str, str, str]:
        # Kept in memory only; never part of a bridge response or log.
        return (client.api_key, client.endpoint, client.model)

    def test_llm_connection(self) -> dict[str, Any]:
        """Make one short, explicit test request using the saved connection."""

        if not self._llm_test_lock.acquire(blocking=False):
            return self.get_llm_settings()
        try:
            client = LLMClient.from_environment(self._data_dir)
            signature = self._llm_signature(client)
            self._llm_probe = (signature, LLMStatus("requesting"), "")
            try:
                client.complete(
                    [{"role": "user", "content": "Reply with OK only."}],
                    temperature=0,
                    max_tokens=8,
                )
            except LLMUnavailable:
                pass
            except Exception:
                client.status = LLMStatus("fallback", "unexpected")
            self._llm_probe = (
                signature, client.status, datetime.now().astimezone().isoformat(timespec="seconds")
            )
            return self.get_llm_settings()
        finally:
            self._llm_test_lock.release()

    def clear_llm_api_key(self) -> dict[str, Any]:
        result = self.save_llm_settings({"clear_api_key": True})
        if result.get("ok"):
            result["message"] = "Saved API key cleared."
        return result

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
                "message": "Preset applied. Values remain experimental until validated.",
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
