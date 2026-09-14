"""pywebview API for Benchmark Lab. Lives only in the Developer build."""

from __future__ import annotations

from pathlib import Path
from threading import Lock, Thread
from typing import Any

from app.settings.storage import load_vision_settings, save_vision_settings
from app.ui.api import DashboardAPI
from developer.benchmark.annotations import filter_samples, mark_selected
from developer.benchmark.comparison import compare_summaries, sort_rows
from developer.benchmark.configs import (
    expand_configs,
    schema_options,
    selection_from_payload,
    settings_to_protection_payload,
)
from developer.benchmark.contracts import BenchmarkRequest
from developer.benchmark.dataset import (
    DatasetError,
    create_dataset,
    import_paths,
    list_datasets,
    open_dataset,
    update_sample,
)
from developer.benchmark.exporter import export_csv, export_json
from developer.benchmark.failures import failure_from_row
from developer.benchmark.high_recall import benchmark_report, load_cases
from developer.benchmark.inference_cache import InferenceCache
from developer.benchmark.jobs import (
    LabProcessJob,
    export_tool_run,
    list_tool_runs,
    save_scalar_report,
)
from developer.benchmark.matrix import job_count, matrix
from developer.benchmark.preview import annotated_data_url, image_data_url
from developer.benchmark.ranking_metrics import ranking_quality, recall_gain
from developer.benchmark.registry import BenchmarkRegistry
from developer.benchmark.runner import BenchmarkRunner
from developer.benchmark.sweep import DEFAULT_PROPOSAL, DEFAULT_STRONG, sweep_thresholds
from developer.benchmark.tags import catalog_payload


class DeveloperDashboardAPI(DashboardAPI):
    """User dashboard API plus Benchmark Lab methods."""

    def __init__(self, *args: Any, data_dir=None, **kwargs: Any) -> None:
        super().__init__(*args, data_dir=data_dir, **kwargs)
        self.window = None
        self._lab_lock = Lock()
        self._dataset = None
        self._runner: BenchmarkRunner | None = None
        self._run = None
        self._error: str | None = None
        self._tool_job: LabProcessJob | None = None
        self._benchmark_registry = BenchmarkRegistry()

    def get_build_edition(self) -> dict[str, Any]:
        return {"ok": True, "edition": "developer", "app_name": "LAVOCADO Developer"}

    def start_protection(self) -> dict[str, Any]:
        with self._lab_lock:
            if self._tool_job is not None and self._tool_job.running:
                return {"ok": False, "message": "Finish or cancel the Lab tool before starting Protection."}
            return super().start_protection()

    def lab_tag_catalog(self) -> dict[str, Any]:
        return {"ok": True, "tags": catalog_payload()}

    def lab_list_datasets(self) -> dict[str, Any]:
        try:
            if self._data_dir is None:
                return {"ok": True, "datasets": []}
            return {"ok": True, "datasets": list_datasets(self._data_dir)}
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not list datasets", error)

    def lab_create_dataset(self, name: str) -> dict[str, Any]:
        try:
            if self._data_dir is None:
                raise DatasetError("No local data directory")
            dataset = create_dataset(self._data_dir, name)
            self._dataset = dataset
            return {"ok": True, "dataset": self._dataset_payload()}
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not create dataset", error)

    def lab_open_dataset(self, path: str | None = None) -> dict[str, Any]:
        try:
            selected = path or self._pick_dataset_file()
            if not selected:
                return {"ok": False, "message": "No dataset selected."}
            dataset = open_dataset(Path(selected))
            self._dataset = dataset
            return {"ok": True, "dataset": self._dataset_payload()}
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not open dataset", error)

    def lab_open_dataset_folder(self, folder: str | None = None) -> dict[str, Any]:
        try:
            selected = folder or self._pick_folder()
            if not selected:
                return {"ok": False, "message": "No dataset folder selected."}
            return self.lab_open_dataset(selected)
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not open dataset folder", error)

    def lab_current_dataset(self) -> dict[str, Any]:
        if self._dataset is None:
            return {"ok": True, "dataset": None}
        return {"ok": True, "dataset": self._dataset_payload()}

    def lab_import_images(
        self,
        paths: list[str] | None = None,
        mode: str = "reference",
        folder: str | None = None,
    ) -> dict[str, Any]:
        try:
            dataset = self._require_dataset()
            selected: list[Path] = []
            if folder:
                selected.append(Path(folder))
            if paths:
                selected.extend(Path(item) for item in paths)
            if not selected:
                picked = self._pick_files(allow_directory=False)
                selected.extend(Path(item) for item in picked)
            result = import_paths(dataset, selected, mode=mode)
            return {"ok": True, "import": result, "dataset": self._dataset_payload()}
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not import images", error)

    def lab_import_folder(self, folder: str | None = None, mode: str = "reference") -> dict[str, Any]:
        try:
            path = folder or self._pick_folder()
            if not path:
                return {"ok": False, "message": "No folder selected."}
            return self.lab_import_images(folder=path, mode=mode)
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not import folder", error)

    def lab_samples(
        self,
        status: str = "all",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        try:
            dataset = self._require_dataset()
            samples = filter_samples(dataset, status=status, tags=tags)
            return {
                "ok": True,
                "samples": [sample.to_dict() for sample in samples],
                "counts": dataset.counts(),
            }
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not list samples", error)

    def lab_preview(self, sample_id: str) -> dict[str, Any]:
        try:
            dataset = self._require_dataset()
            sample = dataset.sample_by_id(sample_id)
            path = dataset.resolve_path(sample)
            return {
                "ok": True,
                "sample": sample.to_dict(),
                "preview": image_data_url(path),
                "missing": not path.is_file(),
            }
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not preview sample", error)

    def lab_annotate(
        self,
        sample_id: str,
        expected: str | None = None,
        excluded: bool | None = None,
        tags: list[str] | None = None,
        expected_visual: str | None = None,
    ) -> dict[str, Any]:
        try:
            dataset = self._require_dataset()
            kwargs: dict[str, Any] = {}
            if expected is not None:
                kwargs["expected"] = expected
            if excluded is not None:
                kwargs["excluded"] = excluded
            if tags is not None:
                kwargs["tags"] = tags
            if expected_visual is not None:
                kwargs["expected_visual"] = expected_visual
            sample = update_sample(dataset, sample_id, **kwargs)
            return {"ok": True, "sample": sample.to_dict(), "counts": dataset.counts()}
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not save annotation", error)

    def lab_annotate_selected(
        self,
        sample_ids: list[str],
        expected: str | None = None,
        excluded: bool | None = None,
    ) -> dict[str, Any]:
        try:
            dataset = self._require_dataset()
            updated = mark_selected(
                dataset,
                sample_ids,
                expected=expected,
                excluded=excluded,
            )
            return {"ok": True, "updated": updated, "counts": dataset.counts()}
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not annotate selection", error)

    def lab_schema_options(self) -> dict[str, Any]:
        return {
            "ok": True,
            "options": schema_options(),
            "categories": self._benchmark_registry.categories(),
        }

    def lab_expand_configs(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            configs = expand_configs(selection_from_payload(payload))
            return {
                "ok": True,
                "count": len(configs),
                "configs": [config.to_dict() for config in configs],
                "options": schema_options(),
            }
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not build configurations", error)

    def lab_start_run(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            dataset = self._require_dataset()
            with self._lab_lock:
                if self._tool_job is not None and self._tool_job.running:
                    return {"ok": False, "message": "A Lab tool is already running."}
                if self._runner is not None and self._runner.progress().get("status") == "running":
                    return {"ok": False, "message": "A benchmark is already running."}
                configs = expand_configs(selection_from_payload(payload))
                if not configs:
                    return {"ok": False, "message": "No valid configurations selected."}
                runner = self._benchmark_registry.runner(
                    BenchmarkRequest(dataset, tuple(configs)),
                    cache=InferenceCache(dataset.cache_dir),
                    session_kwargs={"data_dir": self._data_dir},
                )
                self._runner = runner
                self._error = None
                thread = Thread(target=self._run_worker, args=(runner,), daemon=True)
                thread.start()
            return {"ok": True, "message": "Benchmark started.", "config_count": len(configs)}
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not start benchmark", error)

    def lab_start_tool(self, kind: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Start one isolated diagnostic or capture task, never alongside Protection."""

        try:
            if self._data_dir is None:
                raise DatasetError("No local data directory")
            data = options if isinstance(options, dict) else {}
            with self._lab_lock:
                status = self.get_status()
                if not status.get("ok") or not status.get("can_start"):
                    return {"ok": False, "message": "Stop Protection before running Lab tools."}
                if self._runner is not None and self._runner.progress().get("status") == "running":
                    return {"ok": False, "message": "A dataset benchmark is already running."}
                if self._tool_job is not None and self._tool_job.running:
                    return {"ok": False, "message": "A Lab tool is already running."}
                if self._tool_job is not None:
                    self._tool_job.snapshot()
                arguments = self._tool_arguments(kind, data)
                self._tool_job = self._benchmark_registry.tool_job(
                    kind, arguments, self._data_dir
                )
            return {"ok": True, "message": "Lab tool started.", "job_id": self._tool_job.id}
        except ValueError as error:
            return {"ok": False, "message": str(error)}
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not start Lab tool", error)

    def _tool_arguments(self, kind: str, data: dict[str, Any]) -> list[str]:
        if kind == "diagnostic":
            mode = str(data.get("mode") or "")
            if mode not in {"detector_compare", "ranker_signal", "preprocessor"}:
                raise ValueError("Choose a diagnostic mode")
            arguments = ["--mode", mode]
            if mode != "preprocessor":
                dataset = self._require_dataset()
                arguments.extend(("--dataset", str(dataset.document_path)))
            if mode == "ranker_signal":
                model = str(data.get("model") or "viddexa_nano")
                if model not in {"viddexa_nano", "viddexa_mini"}:
                    raise ValueError("Choose Viddexa Nano or Mini")
                arguments.extend(("--model", model))
            if mode == "preprocessor":
                dimensions: dict[str, int] = {}
                for name, maximum in (("iterations", 1000), ("width", 8192), ("height", 8192), ("size", 2048)):
                    value = int(data.get(name) or {"iterations": 30, "width": 1920, "height": 1080, "size": 640}[name])
                    if not 1 <= value <= maximum:
                        raise ValueError(f"{name} must be 1–{maximum}")
                    dimensions[name] = value
                    arguments.extend((f"--{name}", str(value)))
                if dimensions["width"] * dimensions["height"] > 16_777_216:
                    raise ValueError("Synthetic frame must be at most 16 megapixels")
            return arguments
        if kind == "capture":
            backend = str(data.get("backend") or "both")
            if backend not in {"auto", "native", "mss", "both"}:
                raise ValueError("Unknown capture backend")
            frames = int(data.get("frames") or 30)
            warmup = int(data.get("warmup") if data.get("warmup") is not None else 3)
            if not 1 <= frames <= 10000 or not 0 <= warmup <= 1000:
                raise ValueError("Capture frame count is out of range")
            return ["--backend", backend, "--frames", str(frames), "--warmup", str(warmup)]
        if kind == "stability":
            backend = str(data.get("backend") or "auto")
            if backend not in {"auto", "native", "mss"}:
                raise ValueError("Unknown capture backend")
            duration = int(data.get("duration_seconds") or 3600)
            if not 1 <= duration <= 28800:
                raise ValueError("Stability duration must be 1–28800 seconds")
            return ["--backend", backend, "--duration-seconds", str(duration)]
        raise ValueError("Unknown Lab tool")

    def lab_tool_progress(self) -> dict[str, Any]:
        job = self._tool_job
        return {"ok": True, "job": None if job is None else job.snapshot()}

    def lab_cancel_tool(self) -> dict[str, Any]:
        job = self._tool_job
        if job is None or not job.running:
            return {"ok": False, "message": "No Lab tool is running."}
        job.cancel()
        return {"ok": True, "message": "Lab tool cancelled.", "job": job.snapshot()}

    def lab_tool_history(self) -> dict[str, Any]:
        if self._data_dir is None:
            return {"ok": True, "runs": []}
        return {"ok": True, "runs": list_tool_runs(self._data_dir)}

    def lab_export_tool(self, run_id: str, kind: str = "json", path: str | None = None) -> dict[str, Any]:
        try:
            if kind not in {"json", "csv"}:
                raise ValueError("Choose JSON or CSV")
            runs = list_tool_runs(self._data_dir) if self._data_dir is not None else []
            record = next((item for item in runs if item.get("id") == run_id), None)
            if record is None:
                return {"ok": False, "message": "Lab tool result not found."}
            destination = path or self._pick_save(f"lavocado-lab-{run_id}.{kind}")
            if not destination:
                return {"ok": False, "message": "Export cancelled."}
            target = export_tool_run(record, Path(destination))
            return {"ok": True, "path": str(target)}
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not export Lab tool result", error)

    def lab_high_recall_report(self, path: str | None = None) -> dict[str, Any]:
        try:
            selected = path or self._pick_dataset_file()
            if not selected:
                return {"ok": False, "message": "No cases file selected."}
            report = benchmark_report(load_cases(Path(selected)))
            record = (
                save_scalar_report(self._data_dir, "high_recall_cases", report)
                if self._data_dir is not None else None
            )
            return {"ok": True, "report": report, "run_id": None if record is None else record["id"]}
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not read high-recall cases", error)

    def lab_matrix_preview(self) -> dict[str, Any]:
        return {"ok": True, "matrix": matrix(), "job_count": job_count()}

    def lab_ranking_fixture(
        self, tiles: list[dict[str, Any]], baseline_hits: int = 0,
        with_tile_hits: int | None = None, positives: int = 0,
    ) -> dict[str, Any]:
        try:
            if not isinstance(tiles, list) or len(tiles) > 100:
                raise ValueError("Provide at most 100 tiles")
            quality = ranking_quality(tiles)
            gain = None if with_tile_hits is None else recall_gain(
                baseline_hits=baseline_hits,
                with_tile_hits=with_tile_hits,
                positives=positives,
            )
            result = {"quality": quality, "recall_gain": gain}
            record = (
                save_scalar_report(self._data_dir, "ranking_fixture", result)
                if self._data_dir is not None else None
            )
            return {"ok": True, **result, "run_id": None if record is None else record["id"]}
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not score ranking fixture", error)

    def close_lab_tools(self) -> None:
        if self._tool_job is not None:
            self._tool_job.close()

    def lab_cancel_run(self) -> dict[str, Any]:
        runner = self._runner
        if runner is None:
            return {"ok": False, "message": "No benchmark is running."}
        runner.request_cancel()
        return {"ok": True, "message": "Cancel requested. Completed rows are kept."}

    def lab_progress(self) -> dict[str, Any]:
        runner = self._runner
        payload = {"ok": True, "progress": {"status": "idle"}}
        if runner is not None:
            payload["progress"] = runner.progress()
        if self._error:
            payload["error"] = self._error
        if self._run is not None:
            payload["run"] = self._run_payload()
        return payload

    def lab_results(self) -> dict[str, Any]:
        if self._run is None:
            return {"ok": True, "run": None}
        return {"ok": True, "run": self._run_payload()}

    def lab_failures(
        self,
        kind: str = "all",
        tag: str | None = None,
        config_id: str | None = None,
    ) -> dict[str, Any]:
        if self._run is None:
            return {"ok": True, "rows": []}
        rows = list(self._run.rows)
        if config_id:
            rows = [row for row in rows if row.get("config_id") == config_id]
        if tag:
            rows = [row for row in rows if tag in (row.get("tags") or [])]
        rows = [
            {**row, "failure_kind": case.kind.value if case is not None else None}
            for row in rows
            for case in (failure_from_row(row),)
        ]
        wanted = str(kind or "all").lower()
        if wanted == "correct":
            rows = [row for row in rows if row.get("outcome") in {"tp", "tn", "correct"}]
        elif wanted == "incorrect":
            rows = [row for row in rows if row.get("outcome") == "incorrect"]
        elif wanted != "all":
            rows = [row for row in rows if row.get("failure_kind") == wanted]
        return {"ok": True, "rows": rows}

    def lab_annotated_preview(self, sample_id: str, config_id: str | None = None) -> dict[str, Any]:
        try:
            dataset = self._require_dataset()
            sample = dataset.sample_by_id(sample_id)
            path = dataset.resolve_path(sample)
            detections = []
            if self._run is not None:
                for row in self._run.rows:
                    if row.get("sample_id") != sample_id:
                        continue
                    if config_id and row.get("config_id") != config_id:
                        continue
                    detector = row.get("detector_summary") or {}
                    detections = detector.get("detections") or row.get("raw", {}).get("detections") or []
                    break
            return {
                "ok": True,
                "preview": annotated_data_url(path, detections=detections),
            }
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not build annotated preview", error)

    def lab_compare(self, sort_key: str = "recall") -> dict[str, Any]:
        if self._run is None:
            return {"ok": True, "comparison": {"rows": [], "highlights": {}}}
        comparison = compare_summaries(self._run.configs, self._run.summaries)
        comparison["rows"] = sort_rows(comparison["rows"], sort_key)
        return {"ok": True, "comparison": comparison}

    def lab_sweep(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            dataset = self._require_dataset()
            data = payload if isinstance(payload, dict) else {}
            configs = expand_configs(selection_from_payload(data))
            if not configs:
                return {"ok": False, "message": "Select one configuration to sweep."}
            strong = data.get("strong_values") or list(DEFAULT_STRONG)
            proposal = data.get("proposal_values")
            if proposal is None or proposal == []:
                proposal = list(DEFAULT_PROPOSAL)
            rows = sweep_thresholds(
                dataset,
                configs[0],
                strong_values=[float(value) for value in strong],
                proposal_values=[float(value) for value in proposal],
                cache=InferenceCache(dataset.cache_dir),
            )
            return {"ok": True, "rows": rows}
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not run threshold sweep", error)

    def lab_export(self, kind: str = "json", path: str | None = None) -> dict[str, Any]:
        try:
            if self._run is None:
                return {"ok": False, "message": "No benchmark results to export."}
            destination = path or self._pick_save(
                f"lavocado-benchmark-{self._run.id}.{'csv' if kind == 'csv' else 'json'}"
            )
            if not destination:
                return {"ok": False, "message": "Export cancelled."}
            target = Path(destination)
            if kind == "csv":
                export_csv(self._run, target)
            else:
                export_json(self._run, target)
            return {"ok": True, "path": str(target)}
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not export results", error)

    def lab_apply_config_to_protection(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            if self._data_dir is None:
                raise DatasetError("No local data directory")
            if not config:
                return {"ok": False, "message": "Select a configuration first."}
            from developer.benchmark.configs import BenchmarkConfig

            item = BenchmarkConfig(
                id=str(config.get("id") or "applied"),
                benchmark_target=str(config.get("benchmark_target") or "full_protection_pipeline"),
                detector=str(config.get("detector") or "nudenet_640m"),
                context_model=config.get("context_model"),
                full_input_size=int(config.get("full_input_size") or 640),
                tile_input_size=config.get("tile_input_size"),
                tile_rows=config.get("tile_rows"),
                tile_columns=config.get("tile_columns"),
                tile_overlap=float(config.get("tile_overlap") or 0.0),
                checks_per_scan=config.get("checks_per_scan"),
                threshold_profile=str(config.get("threshold_profile") or "current"),
                settings=dict(config.get("settings") or {}),
            )
            from app.settings.schema import sanitize_vision_settings

            current = load_vision_settings(self._data_dir)
            payload = settings_to_protection_payload(item)
            payload["preset"] = current.preset
            saved = sanitize_vision_settings(payload)
            save_vision_settings(saved, self._data_dir)
            restarted = self._safe_restart_protection()
            return {
                "ok": True,
                "restarted": restarted,
                "message": (
                    "Applied to Developer Protection. "
                    "Protection was restarted."
                    if restarted
                    else "Applied to Developer Protection. Starts on the next protection run."
                ),
            }
        except Exception as error:  # noqa: BLE001
            return self._error_result("Could not apply configuration", error)

    def _run_worker(self, runner: BenchmarkRunner) -> None:
        try:
            self._run = runner.start()
        except Exception as error:  # noqa: BLE001
            self._error = str(error)

    def _require_dataset(self):
        if self._dataset is None:
            raise DatasetError("Open or create a dataset first")
        return self._dataset

    def _dataset_payload(self) -> dict[str, Any]:
        dataset = self._require_dataset()
        return {
            "name": dataset.name,
            "path": str(dataset.root),
            "created_at": dataset.created_at,
            "import_mode": dataset.import_mode,
            **dataset.counts(),
            "samples": [sample.to_dict() for sample in dataset.samples],
        }

    def _run_payload(self) -> dict[str, Any] | None:
        if self._run is None:
            return None
        return self._run.to_dict()

    def _pick_dataset_file(self) -> str | None:
        window = self.window
        if window is None:
            return None
        try:
            import webview

            result = window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=("Dataset JSON (dataset.json;*.json)",),
            )
        except Exception:  # noqa: BLE001 - native dialog failure is cancellation
            return None
        if not result:
            return None
        if isinstance(result, (list, tuple)):
            return str(result[0])
        return str(result)

    def _pick_files(self, allow_directory: bool = False) -> list[str]:
        window = self.window
        if window is None:
            return []
        try:
            import webview

            result = window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=True,
                file_types=("Images (*.jpg;*.jpeg;*.png;*.webp;*.bmp)",),
            )
        except Exception:  # noqa: BLE001 - native dialog failure is cancellation
            return []
        if not result:
            return []
        return [str(item) for item in result]

    def _pick_folder(self) -> str | None:
        window = self.window
        if window is None:
            return None
        try:
            import webview

            result = window.create_file_dialog(webview.FOLDER_DIALOG)
        except Exception:  # noqa: BLE001 - native dialog failure is cancellation
            return None
        if not result:
            return None
        return str(result[0])

    def _pick_save(self, filename: str) -> str | None:
        window = self.window
        if window is None:
            return None
        try:
            import webview

            result = window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=filename,
            )
        except Exception:  # noqa: BLE001 - native dialog failure is cancellation
            return None
        if not result:
            return None
        if isinstance(result, (list, tuple)):
            return str(result[0])
        return str(result)
