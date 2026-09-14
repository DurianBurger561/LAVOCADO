"""Static guardrails for the single supported runtime architecture."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
PRODUCTION_ROOTS = (APP, ROOT / "developer", ROOT / "scripts", ROOT / "lavocado_packaging")


def _files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def _tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def _under(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


def _display(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


class ArchitectureContractTests(unittest.TestCase):
    def test_benchmarks_live_only_in_developer_lab(self) -> None:
        for pattern in ("benchmark_*.py", "bench_*.py", "profile_*.py", "perf_*.py"):
            self.assertEqual(list((ROOT / "scripts").glob(pattern)), [])
        self.assertFalse((ROOT / "scripts" / "soak_capture.py").exists())
        self.assertEqual(list((APP / "vision").glob("*benchmark*.py")), [])

    def test_model_metadata_has_one_owner(self) -> None:
        definitions = [
            _display(path)
            for path in _files(APP)
            for node in ast.walk(_tree(path))
            if isinstance(node, ast.ClassDef) and node.name == "ModelSpec"
        ]
        self.assertEqual(definitions, ["app/vision/model_manifest.py"])
        self.assertNotIn("CONTEXT_MODEL_REVISION", (APP / "config.py").read_text(encoding="utf-8"))
        self.assertNotIn("VIDDEXA_MODEL_FILES =", (APP / "vision" / "model_assets.py").read_text(encoding="utf-8"))

    def test_no_project_package_shadows_pypi_packaging(self) -> None:
        self.assertFalse((ROOT / "packaging").exists())

    def test_single_primary_detector_contract(self) -> None:
        definitions = [
            _display(path)
            for path in _files(APP)
            for node in ast.walk(_tree(path))
            if isinstance(node, ast.ClassDef) and node.name == "PrimaryDetector"
        ]
        self.assertEqual(definitions, ["app/vision/detectors/base.py"])

    def test_display_uses_platform_independent_paths(self) -> None:
        self.assertEqual(
            _display(ROOT / "app" / "platforms" / "capture" / "models.py"),
            "app/platforms/capture/models.py",
        )

    def test_no_legacy_blocklist_symbols(self) -> None:
        violations = []
        forbidden = ("BLOCKED_APPS", "blocklist")
        for root in PRODUCTION_ROOTS:
            for path in _files(root):
                source = path.read_text(encoding="utf-8")
                if any(symbol in source for symbol in forbidden):
                    violations.append(_display(path))
        self.assertEqual(violations, [])

    def test_visual_decisions_use_classification_not_blocked_bool(self) -> None:
        from app.vision.violation_policy import VisualViolationDecision

        fields = VisualViolationDecision.__dataclass_fields__
        self.assertIn("classification", fields)
        self.assertNotIn("blocked", fields)
        self.assertNotIn("is_blocked", fields)

        legacy_results = []
        for path in _files(APP):
            for node in ast.walk(_tree(path)):
                if isinstance(node, ast.Dict) and any(
                    isinstance(key, ast.Constant)
                    and key.value in {"blocked", "is_blocked"}
                    for key in node.keys
                ):
                    legacy_results.append(f"{_display(path)}:{node.lineno}")
        self.assertEqual(legacy_results, [])

    def test_single_capture_frame_definition(self) -> None:
        definitions = []
        stale_definitions = []
        for path in _files(APP):
            for node in ast.walk(_tree(path)):
                if isinstance(node, ast.ClassDef) and node.name == "CaptureFrame":
                    definitions.append(_display(path))
                if isinstance(node, ast.ClassDef) and node.name == "CapturedFrame":
                    stale_definitions.append(_display(path))
        self.assertEqual(definitions, ["app/platforms/capture/models.py"])
        self.assertEqual(stale_definitions, [])

    def test_overlay_does_not_capture_screens(self) -> None:
        violations = []
        self.assertFalse((APP / "vision" / "overlay_process.py").exists())
        for path in _files(APP / "ui" / "overlay"):
            tree = _tree(path)
            for module in _imports(tree):
                if module == "mss" or _under(module, "app.vision.capture") or _under(
                    module, "app.platforms.capture.mss_fallback"
                ):
                    violations.append(f"{_display(path)}: {module}")
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module == "app.platforms.capture"
                    and any(alias.name == "MSSCapture" for alias in node.names)
                ):
                    violations.append(f"{_display(path)}: MSSCapture")
        for path in _files(APP / "vision"):
            for module in _imports(_tree(path)):
                if _under(module, "app.ui.overlay"):
                    violations.append(f"{_display(path)}: {module}")
        self.assertEqual(violations, [])

    def test_app_does_not_depend_on_developer(self) -> None:
        violations = []
        for path in _files(APP):
            for module in _imports(_tree(path)):
                if _under(module, "developer"):
                    violations.append(f"{_display(path)}: {module}")
        self.assertEqual(violations, [])

        user_main = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("developer", user_main)

    def test_context_and_vision_do_not_import_each_other(self) -> None:
        violations = []
        for source_dir, forbidden in (
            (APP / "context", "app.vision"),
            (APP / "vision", "app.context"),
        ):
            for path in _files(source_dir):
                for module in _imports(_tree(path)):
                    if _under(module, forbidden):
                        violations.append(f"{_display(path)}: {module}")
        self.assertEqual(violations, [])

    def test_business_layer_does_not_select_platform(self) -> None:
        business = [APP / "service.py", APP / "protection_runtime.py"]
        business.extend(_files(APP / "context"))
        business.extend(_files(APP / "vision"))
        business.extend(_files(APP / "settings"))
        business.extend(_files(APP / "intervention"))
        violations = []
        for path in business:
            tree = _tree(path)
            for module in _imports(tree):
                if module in {"platform", "platform.system"} or _under(
                    module, "app.platforms.windows"
                ) or _under(module, "app.platforms.macos") or _under(
                    module, "app.platforms.capture.windows_dxgi"
                ) or _under(module, "app.platforms.capture.macos_screencapturekit"):
                    violations.append(f"{_display(path)}: {module}")
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and (
                    isinstance(node.value, ast.Name)
                    and (node.value.id, node.attr)
                    in {("sys", "platform"), ("os", "name"), ("platform", "system")}
                ):
                    violations.append(f"{_display(path)}:{node.lineno}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
