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

class TorchThreadsTests(unittest.TestCase):
    def test_restores_limit_after_backend_initialization(self):
        import sys
        from unittest.mock import Mock
        from app.performance import configure_torch_threads
        torch = Mock()
        torch.get_num_threads.return_value = 8
        torch.get_num_interop_threads.return_value = 4
        with patch.dict(sys.modules, {"torch": torch}), patch.dict(os.environ, {"LAVOCADO_CPU_THREADS": "2"}):
            configure_torch_threads()
        torch.set_num_threads.assert_called_once_with(2)
        torch.set_num_interop_threads.assert_called_once_with(1)

    def test_loaded_interop_executor_does_not_break_model_load(self):
        import sys
        from unittest.mock import Mock
        from app.performance import configure_torch_threads
        torch = Mock()
        torch.get_num_threads.return_value = 2
        torch.get_num_interop_threads.return_value = 4
        torch.set_num_interop_threads.side_effect = RuntimeError("already started")
        with patch.dict(sys.modules, {"torch": torch}):
            configure_torch_threads()
        torch.set_num_threads.assert_not_called()
