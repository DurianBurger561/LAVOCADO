"""CPU pool defaults must stay bounded and user-configurable."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.performance import configure_cpu_threads


class CpuThreadsTests(unittest.TestCase):
    def test_defaults_to_two_threads(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(configure_cpu_threads(), 2)
            self.assertEqual(os.environ["OMP_NUM_THREADS"], "2")
            self.assertEqual(os.environ["OPENBLAS_NUM_THREADS"], "2")
            self.assertEqual(os.environ["MKL_NUM_THREADS"], "2")

    def test_respects_existing_library_limits(self) -> None:
        with patch.dict(
            os.environ,
            {"LAVOCADO_CPU_THREADS": "4", "OMP_NUM_THREADS": "1"},
            clear=True,
        ):
            self.assertEqual(configure_cpu_threads(), 4)
            self.assertEqual(os.environ["OMP_NUM_THREADS"], "1")
            self.assertEqual(os.environ["OPENBLAS_NUM_THREADS"], "4")

    def test_invalid_override_uses_default(self) -> None:
        with patch.dict(os.environ, {"LAVOCADO_CPU_THREADS": "many"}, clear=True):
            self.assertEqual(configure_cpu_threads(), 2)

    def test_nudenet_onnx_session_uses_the_limit(self) -> None:
        from app.vision.detectors.nudenet import BoundedNudeDetector

        with patch.dict(os.environ, {"LAVOCADO_CPU_THREADS": "2"}):
            detector = BoundedNudeDetector()
        options = detector.onnx_session.get_session_options()
        self.assertEqual(options.intra_op_num_threads, 2)
        self.assertEqual(options.inter_op_num_threads, 1)


if __name__ == "__main__":
    unittest.main()
