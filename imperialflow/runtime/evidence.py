import hashlib
import re
from pathlib import Path

from .errors import require
from .models import EvidenceArtifact


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def within_root(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    require(path.is_relative_to(root.resolve()), "ROLE_CAPABILITY_VIOLATION", f"Path outside workspace: {name}")
    return path


def selector_span(text: str, selector: str):
    # Select real record lines, not quoted selector strings in appended JSON.
    lead = len(selector) - len(selector.lstrip("\n"))
    literal = selector.lstrip("\n")
    matches = list(re.finditer(r"(?m)^" + re.escape(literal), text))
    require(len(matches) == 1, "EVIDENCE_MISSING", "Evidence selector must identify one record line")
    start = matches[0].start() - lead
    require(start >= 0 and text[start:matches[0].end()] == selector,
            "EVIDENCE_MISSING", "Evidence selector boundary")
    return start, matches[0].end()


def artifact_bytes(root: Path, artifact: EvidenceArtifact) -> bytes:
    path = within_root(root, artifact.path)
    require(path.is_file(), "EVIDENCE_MISSING", artifact.path)
    data = path.read_bytes()
    if artifact.start:
        text = data.decode("utf-8-sig").replace("\r\n", "\n")
        start, _ = selector_span(text, artifact.start)
        end, _ = selector_span(text, artifact.end)
        require(end > start, "EVIDENCE_MISSING", "Evidence section order")
        # Marker selectors exclude markers; heading selectors include the heading.
        offset = len(artifact.start) if artifact.start.startswith("<!--") else 0
        text = text[start + offset:end]
        data = text.encode("utf-8")
    if artifact.normalization in {"LF", "PACKAGE"}:
        text = data.decode("utf-8-sig").replace("\r\n", "\n").strip("\n") + "\n"
        if artifact.normalization == "PACKAGE":
            text = re.sub(r"(?m)^EXECUTION_PACKAGE_SHA256: [0-9a-f]{64}",
                          "EXECUTION_PACKAGE_SHA256: [omitted]", text)
        data = text.encode("utf-8")
    return data


def verify_artifact(root: Path, artifact: EvidenceArtifact):
    require(artifact.status != "VOID", "VOID_ARTIFACT_REFERENCE", artifact.id)
    require(digest(artifact_bytes(root, artifact)) == artifact.sha256,
            "STATE_CONFLICT", f"Evidence changed: {artifact.id}")
    # An allegedly VALID selector may not lie inside an explicitly VOID archive.
    if artifact.start:
        text = within_root(root, artifact.path).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        index, _ = selector_span(text, artifact.start)
        end, _ = selector_span(text, artifact.end)
        for match in re.finditer(r"<!-- BEGIN VOID UNAUTHORIZED (\w+) RECORD -->[\s\S]*?<!-- END VOID UNAUTHORIZED \1 RECORD -->", text):
            require(not (index < match.end() and end > match.start()), "VOID_ARTIFACT_REFERENCE", artifact.id)
    else:
        require(b"<!-- BEGIN VOID UNAUTHORIZED" not in artifact_bytes(root, artifact),
                "VOID_ARTIFACT_REFERENCE", "Mixed legacy task file requires precise valid section selectors")
