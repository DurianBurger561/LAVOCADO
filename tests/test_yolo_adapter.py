"""Tests for the optional YOLO11 evidence adapter."""

import tempfile
import unittest
from pathlib import Path

import numpy as np

from app.vision.violation_policy import ViolationEvidenceType
from app.vision.yolo_adapter import (
    UltralyticsYoloModel,
    Yolo11Adapter,
    detections_to_evidence,
    load_yolo_adapter,
    xyxy_to_xywh,
    yolo_is_requested,
)
from app.vision.model_assets import resolve_yolo_model_path


class FakeYolo:
    def __init__(self, detections: list[dict[str, object]]) -> None:
        self.detections = detections
        self.received = 0

    def detect(self, image: np.ndarray) -> list[dict[str, object]]:
        self.received += 1
        self.image_shape = image.shape
        return self.detections


class FakeUltralyticsResult:
    def __init__(self) -> None:
        self.names = {0: "blowjob", 1: "person"}
        self.boxes = type(
            "Boxes",
            (),
            {
                "xyxy": [[10.0, 20.0, 40.0, 60.0], [1.0, 1.0, 2.0, 2.0]],
                "conf": [0.91, 0.4],
                "cls": [0, 1],
            },
        )()


class FakeUltralyticsYOLO:
    def __init__(self, results: list[FakeUltralyticsResult]) -> None:
        self._results = results
        self.received_shape: tuple[int, ...] | None = None

    def predict(self, image: np.ndarray, verbose: bool = True) -> list[FakeUltralyticsResult]:
        del verbose
        self.received_shape = image.shape
        self.received_channel = tuple(int(value) for value in image[0, 0])
        return self._results


class YoloAdapterTests(unittest.TestCase):
    def test_detect_evidence_uses_shared_policy(self) -> None:
        model = FakeYolo(
            [{"class": "oral-sex", "score": 0.92, "box": [2, 2, 8, 8]}]
        )
        adapter = Yolo11Adapter(model)

        evidence = adapter.detect_evidence(
            np.zeros((16, 16, 3), dtype=np.uint8),
            frame_sequence=9,
        )

        self.assertEqual(model.received, 1)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].evidence_type, ViolationEvidenceType.SEXUAL_ACT)
        self.assertEqual(evidence[0].frame_sequence, 9)
        self.assertEqual(evidence[0].model, "yolo11")

    def test_xyxy_boxes_are_converted_for_roi_mapping(self) -> None:
        self.assertEqual(xyxy_to_xywh((10, 20, 40, 60)), (10.0, 20.0, 30.0, 40.0))
        model = FakeYolo(
            [{
                "class": "penis",
                "score": 0.8,
                "box": [10, 20, 40, 60],
                "box_format": "xyxy",
            }]
        )

        evidence = Yolo11Adapter(model).detect_evidence(
            np.zeros((80, 80, 3), dtype=np.uint8)
        )

        self.assertEqual(evidence[0].bbox, (10.0, 20.0, 30.0, 40.0))
        self.assertEqual(evidence[0].evidence_type, ViolationEvidenceType.GENITAL_EXPOSURE)

    def test_ultralytics_wrapper_emits_xywh_and_skips_unmapped_classes(self) -> None:
        backend = FakeUltralyticsYOLO([FakeUltralyticsResult()])
        bgr = np.zeros((8, 8, 3), dtype=np.uint8)
        bgr[0, 0] = (10, 20, 30)

        detections = UltralyticsYoloModel(backend).detect(bgr)

        self.assertEqual(backend.received_channel, (30, 20, 10))
        self.assertEqual([item["class"] for item in detections], ["blowjob", "person"])
        self.assertEqual(detections[0]["box"], [10.0, 20.0, 30.0, 40.0])
        self.assertEqual(detections[0]["box_format"], "xywh")
        evidence = detections_to_evidence(detections)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0].evidence_type, ViolationEvidenceType.SEXUAL_ACT)

    def test_non_array_input_returns_no_evidence(self) -> None:
        adapter = Yolo11Adapter(FakeYolo([]))

        self.assertEqual(adapter.detect_evidence(1, frame_sequence=1), [])  # type: ignore[arg-type]

    def test_loader_stays_off_by_default(self) -> None:
        self.assertFalse(yolo_is_requested(enabled=False, environ={}))
        self.assertIsNone(load_yolo_adapter(enabled=False, environ={}))

    def test_loader_uses_injected_factory_when_enabled(self) -> None:
        adapter = load_yolo_adapter(
            enabled=True,
            model_factory=lambda: FakeYolo([]),
            environ={},
        )

        self.assertIsNotNone(adapter)

    def test_loader_survives_missing_ultralytics(self) -> None:
        def factory() -> FakeYolo:
            raise ImportError("ultralytics")

        with self.assertLogs("app.vision.yolo_adapter", level="WARNING"):
            adapter = load_yolo_adapter(
                enabled=True,
                model_factory=factory,
                environ={},
            )

        self.assertIsNone(adapter)

    def test_env_path_requests_yolo_without_config_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "custom.pt"
            model_path.touch()
            environ = {"LAVOCADO_YOLO_MODEL": str(model_path)}

            self.assertTrue(yolo_is_requested(enabled=False, environ=environ))
            self.assertEqual(
                resolve_yolo_model_path(environ=environ, root=Path("unused")),
                model_path,
            )


if __name__ == "__main__":
    unittest.main()
