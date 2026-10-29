"""Downloads the two pinned, hash-checked model files. Usage: python -m recruiter_bot.linking.model_files"""
import hashlib
import shutil
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "models"

EMBEDDING_REPOSITORY = "Xenova/bge-small-en-v1.5"
EMBEDDING_COMMIT = "ea104dacec62c0de699686887e3f920caeb4f3e3"

NLI_REPOSITORY = "Xenova/nli-deberta-v3-xsmall"
NLI_COMMIT = "2a4f614a701367a02d51389039afc998faeda637"


@dataclass(frozen=True)
class ModelFile:
    repository: str
    commit: str
    path_in_repository: str
    local_name: str
    size: int
    sha256: str

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repository}/resolve/{self.commit}/{self.path_in_repository}"

    @property
    def local_path(self) -> Path:
        return MODELS_DIR / self.local_name


# Pinned SHA-256 per file: Hugging Face's for .onnx, computed once for the JSON files.
MODEL_FILES = [
    ModelFile(EMBEDDING_REPOSITORY, EMBEDDING_COMMIT, "onnx/model_quantized.onnx", "embedding/model.onnx",
              34014426, "6c9c6101a956d62dfb5e7190c538226c0c5bb9cb27b651234b6df063ee7dbfe4"),
    ModelFile(EMBEDDING_REPOSITORY, EMBEDDING_COMMIT, "tokenizer.json", "embedding/tokenizer.json",
              711396, "d241a60d5e8f04cc1b2b3e9ef7a4921b27bf526d9f6050ab90f9267a1f9e5c66"),
    ModelFile(NLI_REPOSITORY, NLI_COMMIT, "onnx/model_quantized.onnx", "nli/model.onnx",
              87246587, "3fac2500c45c75af42c7711de0d1b93d59577456100208be0dc1f9e8811946b6"),
    ModelFile(NLI_REPOSITORY, NLI_COMMIT, "tokenizer.json", "nli/tokenizer.json",
              8656551, "a86f883318afa11c8c10466f1bf4efaeb6ded28a52cbe57217a8fa0d0a2a87df"),
    ModelFile(NLI_REPOSITORY, NLI_COMMIT, "config.json", "nli/config.json",
              1038, "ec0bd14cc28640326474399cd61d38ccd52b64900228799d0f81debda8c4bc53"),
]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_present_and_valid(model_file: ModelFile) -> bool:
    path = model_file.local_path
    return path.exists() and path.stat().st_size == model_file.size and sha256_of(path) == model_file.sha256


def download(model_file: ModelFile) -> None:
    """Downloads to a temporary file and only keeps it if size and hash match."""
    model_file.local_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = model_file.local_path.with_suffix(model_file.local_path.suffix + ".part")
    with urllib.request.urlopen(model_file.url) as response, temporary_path.open("wb") as file:
        shutil.copyfileobj(response, file)

    size = temporary_path.stat().st_size
    digest = sha256_of(temporary_path)
    if size != model_file.size or digest != model_file.sha256:
        temporary_path.unlink()
        raise RuntimeError(
            f"{model_file.url}: expected {model_file.size} bytes with SHA-256 {model_file.sha256}, "
            f"got {size} bytes with SHA-256 {digest}"
        )
    temporary_path.replace(model_file.local_path)


def main() -> None:
    for model_file in MODEL_FILES:
        if is_present_and_valid(model_file):
            print(f"ok          {model_file.local_name}")
            continue
        print(f"downloading {model_file.local_name} ({model_file.size / 1_000_000:.1f} MB)")
        download(model_file)
    print(f"All model files are in {MODELS_DIR}")


if __name__ == "__main__":
    sys.exit(main())
