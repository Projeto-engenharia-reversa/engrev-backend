import importlib
import io
import zipfile
from pathlib import Path
from uuid import uuid4

from app.core.exceptions import UploadError

UPLOAD_ROOT = Path("storage/uploads")
MAX_FILE_SIZE = 5 * 1024 * 1024

BINARY_SAMPLE_SIZE = 8 * 1024


def looks_binary(content: bytes, sample: int = BINARY_SAMPLE_SIZE) -> bool:
    return b"\x00" in content[:sample]


def _safe_member_name(member: str) -> str:
    name = member.replace("\\", "/")
    name = name.lstrip("/")
    if ".." in name.split("/"):
        raise UploadError("O ZIP contém caminhos inválidos (traversal)")
    return name


def _eligible(data: bytes, size: int) -> tuple[bool, str | None]:
    if size > MAX_FILE_SIZE:
        return False, "Arquivo excede o limite de 5MB"
    if looks_binary(data):
        return False, "Arquivo binário ou ilegível"
    return True, None


def extract_zip(content: bytes, project_id: int) -> tuple[Path, list[dict], int, int]:
    target_dir = UPLOAD_ROOT / str(project_id) / uuid4().hex
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise UploadError("O arquivo enviado não é um ZIP válido")
    manifest: list[dict] = []
    accepted = 0
    should_ignore = importlib.import_module("app.pipeline.steps.1_scan.ignore").should_ignore
    for member in archive.infolist():
        if member.is_dir():
            continue
        name = _safe_member_name(member.filename)
        if should_ignore(Path(name)):
            continue
        data = archive.read(member)
        ok, reason = _eligible(data, member.file_size)
        manifest.append({"path": name, "size_bytes": member.file_size, "status": "ok" if ok else "excluded", "reason": reason})
        if not ok:
            continue
        destination = target_dir / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        accepted += 1
    return target_dir, manifest, len(manifest), accepted
