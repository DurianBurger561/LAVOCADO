"""Immutable release-model metadata shared by runtime, downloads, and packaging."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class ModelRole(str, Enum):
    PRIMARY_DETECTOR = "primary"
    REGION_RANKER = "region_ranker"


@dataclass(frozen=True, slots=True)
class PinnedModelFile:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    label: str
    role: ModelRole
    source: str
    required: bool
    downloadable: bool = True
    revision: str | None = None
    huggingface_id: str | None = None
    bundled_path: str = ""
    required_files: tuple[PinnedModelFile, ...] = ()
    download_url: str | None = None


NUDENET_640M_FILENAME = "640m.onnx"
NUDENET_640M_SIZE = 103_538_690
NUDENET_640M_SHA256 = (
    "04fe3d77980780c1f8297dc6d7f942fd5b3abe6942a188f742a85241e4f634eb"
)
NUDENET_640M_DOWNLOAD_URL = (
    "https://api.github.com/repos/notAI-tech/NudeNet/releases/assets/176832019"
)
YOLO11_NSFW_SMALL_FILENAME = "yolo11.pt"
YOLO11_NSFW_SMALL_SIZE = 19_159_379
YOLO11_NSFW_SMALL_SHA256 = (
    "cd268d5ac84058fc9f3681bcc5446775e7ca1fdcf53948277a8b7ba12055eb10"
)
YOLO11_NSFW_SMALL_REPO = "erax-ai/EraX-NSFW-V1.0"
YOLO11_NSFW_SMALL_REVISION = "aea60ac8d2ebcbe0fcbb29e623eba99945b988a6"
YOLO11_NSFW_SMALL_REMOTE_NAME = "erax_nsfw_yolo11s.pt"
YOLO11_NSFW_SMALL_DOWNLOAD_URL = (
    "https://huggingface.co/erax-ai/EraX-NSFW-V1.0/resolve/"
    f"{YOLO11_NSFW_SMALL_REVISION}/{YOLO11_NSFW_SMALL_REMOTE_NAME}"
)
VIDDEXA_NANO_REPO = "viddexa/nsfw-detection-2-nano"
VIDDEXA_NANO_REVISION = "12e57200346246b37382f746e4d94d10b014f6a1"
VIDDEXA_MINI_REPO = "viddexa/nsfw-detection-2-mini"
VIDDEXA_MINI_REVISION = "15f61cddc0a1a2a9176f018fb6838ef92c8163cc"

VIDDEXA_MODEL_FILES: Mapping[str, tuple[PinnedModelFile, ...]] = MappingProxyType({
    "viddexa_nano": (
        PinnedModelFile("model.safetensors", 16_270_500, "011ef883033b5908994a06d3b6dcfbf55498206afc1cb55849f918588c7dfcba"),
        PinnedModelFile("config.json", 1_577, "29983c0fe447a47372b5a931eaeae085002855b98a32f9ecffd5572dd03d818f"),
        PinnedModelFile("preprocessor_config.json", 495, "f678895d3b0b6d95f32b0ab9d683c127c69b5f45939f82932cb90eb58bffa51e"),
    ),
    "viddexa_mini": (
        PinnedModelFile("model.safetensors", 70_823_532, "b77f531d1d90bc8268f6ec18bd6dee7b2ba19277f53267f17cfebc12626f49a4"),
        PinnedModelFile("config.json", 1_384, "3248bae9dae0230a7bac5878322b637dc26dd427cf17b8224aaeeb8fc9c62903"),
        PinnedModelFile("preprocessor_config.json", 495, "249d72557e900bad1ce5ed790e3aa628cbbe96484ee6ec67991a03d29609b392"),
    ),
})

CATALOG: tuple[ModelSpec, ...] = (
    ModelSpec(
        "nudenet_640m", "NudeNet 640m", ModelRole.PRIMARY_DETECTOR,
        "github:notAI-tech/NudeNet@v3.4-weights", True,
        revision=NUDENET_640M_SHA256[:12], bundled_path="models/640m.onnx",
        required_files=(PinnedModelFile(NUDENET_640M_FILENAME, NUDENET_640M_SIZE, NUDENET_640M_SHA256),),
        download_url=NUDENET_640M_DOWNLOAD_URL,
    ),
    ModelSpec(
        "yolo11_nsfw_small", "YOLO11 NSFW Small", ModelRole.PRIMARY_DETECTOR,
        f"huggingface:{YOLO11_NSFW_SMALL_REPO}", True,
        revision=YOLO11_NSFW_SMALL_REVISION, huggingface_id=YOLO11_NSFW_SMALL_REPO,
        bundled_path="models/yolo11.pt",
        required_files=(PinnedModelFile(YOLO11_NSFW_SMALL_FILENAME, YOLO11_NSFW_SMALL_SIZE, YOLO11_NSFW_SMALL_SHA256),),
        download_url=YOLO11_NSFW_SMALL_DOWNLOAD_URL,
    ),
    ModelSpec(
        "viddexa_nano", "Viddexa Nano", ModelRole.REGION_RANKER,
        f"huggingface:{VIDDEXA_NANO_REPO}", True,
        revision=VIDDEXA_NANO_REVISION, huggingface_id=VIDDEXA_NANO_REPO,
        bundled_path="models/viddexa_nano", required_files=VIDDEXA_MODEL_FILES["viddexa_nano"],
    ),
    ModelSpec(
        "viddexa_mini", "Viddexa Mini", ModelRole.REGION_RANKER,
        f"huggingface:{VIDDEXA_MINI_REPO}", True,
        revision=VIDDEXA_MINI_REVISION, huggingface_id=VIDDEXA_MINI_REPO,
        bundled_path="models/viddexa_mini", required_files=VIDDEXA_MODEL_FILES["viddexa_mini"],
    ),
)

CATALOG_MODEL_IDS = tuple(spec.id for spec in CATALOG)


def required_model_ids(catalog: tuple[ModelSpec, ...] = CATALOG) -> tuple[str, ...]:
    return tuple(spec.id for spec in catalog if spec.required)


REQUIRED_MODEL_IDS = required_model_ids()


def spec_by_id(model_id: str) -> ModelSpec | None:
    return next((spec for spec in CATALOG if spec.id == model_id), None)
