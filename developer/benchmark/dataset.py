"""Local developer dataset. Images are never captured from Protection."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal

from developer.benchmark import SCHEMA_VERSION
from developer.benchmark.tags import normalize_tags

EXPECTED_BLOCK = "block"
EXPECTED_ALLOW = "allow"
ALLOWED_EXPECTED = frozenset({EXPECTED_BLOCK, EXPECTED_ALLOW})
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp"})
IMPORT_REFERENCE = "reference"
IMPORT_COPY = "copy"
DATASET_FILENAME = "dataset.json"
IMAGES_DIRNAME = "images"
CACHE_DIRNAME = "cache"
RESULTS_DIRNAME = "results"
ImportMode = Literal["reference", "copy"]


class DatasetError(ValueError):
    """User-facing dataset problem."""


@dataclass
class BenchmarkSample:
    id: str
    path: str
    expected: str | None
    excluded: bool
    tags: set[str] = field(default_factory=set)
    source_path: str | None = None
    content_hash: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "expected": self.expected,
            "excluded": bool(self.excluded),
            "tags": sorted(self.tags),
            "source_path": self.source_path,
            "content_hash": self.content_hash,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> BenchmarkSample:
        expected = payload.get("expected")
        if expected is None or expected == "":
            normalized_expected = None
        else:
            normalized_expected = str(expected).strip().lower()
            if normalized_expected not in ALLOWED_EXPECTED:
                raise DatasetError("Ground truth must be block, allow, or unlabelled")
        return cls(
            id=str(payload.get("id") or "").strip(),
            path=str(payload.get("path") or "").strip(),
            expected=normalized_expected,
            excluded=bool(payload.get("excluded")),
            tags=normalize_tags(payload.get("tags")),
            source_path=(
                None
                if payload.get("source_path") in (None, "")
                else str(payload.get("source_path"))
            ),
            content_hash=(
                None
                if payload.get("content_hash") in (None, "")
                else str(payload.get("content_hash"))
            ),
        )


@dataclass
class BenchmarkDataset:
    name: str
    root: Path
    created_at: str
    samples: list[BenchmarkSample] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION
    import_mode: str = IMPORT_REFERENCE

    @property
    def document_path(self) -> Path:
        return self.root / DATASET_FILENAME

    @property
    def images_dir(self) -> Path:
        return self.root / IMAGES_DIRNAME

    @property
    def cache_dir(self) -> Path:
        return self.root / CACHE_DIRNAME

    @property
    def results_dir(self) -> Path:
        return self.root / RESULTS_DIRNAME

    def sample_by_id(self, sample_id: str) -> BenchmarkSample:
        for sample in self.samples:
            if sample.id == sample_id:
                return sample
        raise DatasetError(f"Unknown sample: {sample_id}")

    def resolve_path(self, sample: BenchmarkSample) -> Path:
        stored = Path(sample.path)
        if stored.is_absolute():
            return stored
        return (self.root / stored).resolve()

    def counts(self) -> dict[str, int]:
        labelled = [item for item in self.samples if item.expected in ALLOWED_EXPECTED]
        return {
            "total": len(self.samples),
            "labelled": len(labelled),
            "unlabelled": sum(1 for item in self.samples if item.expected is None),
            "block": sum(1 for item in labelled if item.expected == EXPECTED_BLOCK),
            "allow": sum(1 for item in labelled if item.expected == EXPECTED_ALLOW),
            "excluded": sum(1 for item in self.samples if item.excluded),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "name": self.name,
            "created_at": self.created_at,
            "import_mode": self.import_mode,
            "samples": [sample.to_dict() for sample in self.samples],
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def datasets_root(data_dir: Path) -> Path:
    return Path(data_dir) / "benchmark_data"


def slug_name(name: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in str(name).strip()
    ).strip("-_")
    return cleaned or "dataset"


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def is_image_path(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def validate_image(path: Path) -> None:
    if not path.is_file():
        raise DatasetError(f"Missing image: {path}")
    if not is_image_path(path):
        raise DatasetError(f"Unsupported image type: {path.suffix}")
    try:
        from PIL import Image

        with Image.open(path) as image:
            image.verify()
    except DatasetError:
        raise
    except Exception as error:  # noqa: BLE001 - convert decoder failures
        raise DatasetError(f"Invalid image: {path.name}") from error


def next_sample_id(samples: list[BenchmarkSample]) -> str:
    highest = 0
    for sample in samples:
        try:
            highest = max(highest, int(sample.id))
        except (TypeError, ValueError):
            continue
    return f"{highest + 1:06d}"


def create_dataset(data_dir: Path, name: str) -> BenchmarkDataset:
    cleaned = str(name or "").strip()
    if not cleaned:
        raise DatasetError("Dataset name is required")
    root = datasets_root(data_dir) / slug_name(cleaned)
    if root.exists() and any(root.iterdir()):
        raise DatasetError(f"Dataset already exists: {cleaned}")
    dataset = BenchmarkDataset(
        name=cleaned,
        root=root,
        created_at=utc_now(),
    )
    _ensure_layout(dataset)
    save_dataset(dataset)
    return dataset


def open_dataset(path: Path) -> BenchmarkDataset:
    document = Path(path)
    if document.is_dir():
        document = document / DATASET_FILENAME
    if not document.is_file():
        raise DatasetError(f"Dataset not found: {document}")
    try:
        with document.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise DatasetError("Could not read dataset.json") from error
    if not isinstance(payload, dict):
        raise DatasetError("dataset.json must be an object")
    samples = [
        BenchmarkSample.from_dict(item)
        for item in payload.get("samples") or []
        if isinstance(item, dict)
    ]
    for sample in samples:
        if not sample.id or not sample.path:
            raise DatasetError("Every sample needs an id and path")
    dataset = BenchmarkDataset(
        name=str(payload.get("name") or document.parent.name),
        root=document.parent.resolve(),
        created_at=str(payload.get("created_at") or utc_now()),
        samples=samples,
        schema_version=int(payload.get("schema_version") or SCHEMA_VERSION),
        import_mode=str(payload.get("import_mode") or IMPORT_REFERENCE),
    )
    _ensure_layout(dataset)
    return dataset


def save_dataset(dataset: BenchmarkDataset) -> Path:
    _ensure_layout(dataset)
    path = dataset.document_path
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = dataset.to_dict()
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)
    return path


def list_datasets(data_dir: Path) -> list[dict[str, Any]]:
    root = datasets_root(data_dir)
    if not root.is_dir():
        return []
    listed: list[dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        document = child / DATASET_FILENAME
        if not document.is_file():
            continue
        try:
            dataset = open_dataset(document)
        except DatasetError:
            continue
        listed.append(
            {
                "name": dataset.name,
                "path": str(dataset.root),
                "created_at": dataset.created_at,
                **dataset.counts(),
            }
        )
    return listed


def import_paths(
    dataset: BenchmarkDataset,
    paths: Iterable[Path],
    *,
    mode: str,
) -> dict[str, Any]:
    import_mode = IMPORT_COPY if mode == IMPORT_COPY else IMPORT_REFERENCE
    dataset.import_mode = import_mode
    added = 0
    skipped_duplicate = 0
    skipped_invalid = 0
    existing_hashes = {
        sample.content_hash for sample in dataset.samples if sample.content_hash
    }
    existing_paths = {str(dataset.resolve_path(sample)) for sample in dataset.samples}
    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_dir():
            children = sorted(
                child for child in path.rglob("*") if child.is_file() and is_image_path(child)
            )
        elif path.is_file():
            children = [path]
        else:
            skipped_invalid += 1
            continue
        for child in children:
            try:
                validate_image(child)
                digest = hash_file(child)
            except DatasetError:
                skipped_invalid += 1
                continue
            resolved = str(child.resolve())
            if digest in existing_hashes or resolved in existing_paths:
                skipped_duplicate += 1
                continue
            sample_id = next_sample_id(dataset.samples)
            if import_mode == IMPORT_COPY:
                dataset.images_dir.mkdir(parents=True, exist_ok=True)
                destination = dataset.images_dir / f"{sample_id}{child.suffix.lower()}"
                shutil.copy2(child, destination)
                stored_path = f"{IMAGES_DIRNAME}/{destination.name}"
            else:
                stored_path = str(child.resolve())
            sample = BenchmarkSample(
                id=sample_id,
                path=stored_path,
                expected=None,
                excluded=False,
                tags=set(),
                source_path=str(child.resolve()),
                content_hash=digest,
            )
            dataset.samples.append(sample)
            existing_hashes.add(digest)
            existing_paths.add(str(dataset.resolve_path(sample)))
            added += 1
    save_dataset(dataset)
    return {
        "added": added,
        "skipped_duplicate": skipped_duplicate,
        "skipped_invalid": skipped_invalid,
        **dataset.counts(),
    }


def update_sample(
    dataset: BenchmarkDataset,
    sample_id: str,
    *,
    expected: str | None | object = ...,
    excluded: bool | object = ...,
    tags: object = ...,
) -> BenchmarkSample:
    sample = dataset.sample_by_id(sample_id)
    if expected is not ...:
        if expected is None or expected == "" or expected == "unlabelled":
            sample.expected = None
        else:
            normalized = str(expected).strip().lower()
            if normalized not in ALLOWED_EXPECTED:
                raise DatasetError("Ground truth only allows block or allow")
            sample.expected = normalized
    if excluded is not ...:
        sample.excluded = bool(excluded)
    if tags is not ...:
        sample.tags = normalize_tags(tags)
    save_dataset(dataset)
    return sample


def update_samples(
    dataset: BenchmarkDataset,
    sample_ids: Iterable[str],
    *,
    expected: str | None | object = ...,
    excluded: bool | object = ...,
    tags: object = ...,
) -> int:
    count = 0
    for sample_id in sample_ids:
        update_sample(
            dataset,
            sample_id,
            expected=expected,
            excluded=excluded,
            tags=tags,
        )
        count += 1
    return count


def eligible_for_metrics(sample: BenchmarkSample) -> bool:
    return (not sample.excluded) and sample.expected in ALLOWED_EXPECTED


def _ensure_layout(dataset: BenchmarkDataset) -> None:
    dataset.root.mkdir(parents=True, exist_ok=True)
    dataset.images_dir.mkdir(parents=True, exist_ok=True)
    dataset.cache_dir.mkdir(parents=True, exist_ok=True)
    dataset.results_dir.mkdir(parents=True, exist_ok=True)
