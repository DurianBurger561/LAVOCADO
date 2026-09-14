"""Shared request and environment contracts for the Benchmark Lab."""

from __future__ import annotations

import platform
import sys
from dataclasses import asdict, dataclass

from developer.benchmark.configs import BenchmarkConfig
from developer.benchmark.dataset import BenchmarkDataset


@dataclass(frozen=True, slots=True)
class BenchmarkRequest:
    dataset: BenchmarkDataset
    configs: tuple[BenchmarkConfig, ...]

    def __post_init__(self) -> None:
        if not self.configs:
            raise ValueError("benchmark request needs at least one configuration")


@dataclass(frozen=True, slots=True)
class BenchmarkEnvironment:
    os: str
    architecture: str
    python: str

    @classmethod
    def current(cls) -> BenchmarkEnvironment:
        """Capture coarse reproducibility fields, never hostname or user identity."""

        return cls(
            os=platform.system(),
            architecture=platform.machine(),
            python=f"{sys.version_info.major}.{sys.version_info.minor}",
        )

    def to_dict(self) -> dict[str, str]:
        return asdict(self)
