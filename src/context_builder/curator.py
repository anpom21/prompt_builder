from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import ast
import re
import subprocess
import time

from .core import FileRecord, Workspace


TIER_HIGH = "high"
TIER_POTENTIAL = "potential"
TIER_LOW = "low"

_TIER_ORDER = {TIER_HIGH: 0, TIER_POTENTIAL: 1, TIER_LOW: 2}
_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_./:-]{2,}")
_QUOTED_PHRASE_PATTERN = re.compile(r"['\"]([^'\"\n]{8,})['\"]")
_STOP_WORDS = {
    "about", "after", "again", "also", "and", "are", "been", "before",
    "build", "could", "does", "file", "files", "from", "have", "into",
    "make", "more", "only", "other", "should", "that", "the", "their",
    "then", "there", "these", "this", "those", "through", "user", "using",
    "want", "when", "where", "which", "with", "would",
}
_SYMBOL_CACHE: dict[str, frozenset[str]] = {}

_ASSET_SUFFIXES = {
    ".bmp", ".gif", ".ico", ".jpeg", ".jpg", ".lock", ".pdf", ".png",
    ".svg", ".webp", ".woff", ".woff2",
}


@dataclass(frozen=True, slots=True)
class CuratorRecommendation:
    file_id: str
    score: int
    tier: str
    recommended_mode: str
    reasons: tuple[str, ...]

    @property
    def tier_label(self) -> str:
        return {
            TIER_HIGH: "Highly relevant",
            TIER_POTENTIAL: "Potentially relevant",
            TIER_LOW: "Probably unnecessary",
        }[self.tier]


def rank_workspace_files(
    workspace: Workspace,
    user_prompt: str,
    *,
    explicit_file_ids: Iterable[str] = (),
) -> list[CuratorRecommendation]:
    """Rank workspace files using explainable, local-only relevance signals."""
    explicit_ids = {
        file_id for file_id in explicit_file_ids if file_id in workspace.files
    }
    direct_ids = {
        record.id
        for record in workspace.files.values()
        if record.source_kind == "direct_file" or record.context_type == "file_from_user"
    }
    seed_ids = direct_ids | explicit_ids
    prompt_tokens = _prompt_tokens(user_prompt)
    prompt_phrases = _prompt_phrases(user_prompt)
    changed_paths = _git_changed_paths(workspace.project_root)
    forward_distances = _dependency_distances(workspace, seed_ids, reverse=False)
    reverse_distances = _dependency_distances(workspace, seed_ids, reverse=True)
    related_stems = {
        _relationship_stem(workspace.files[file_id].filename)
        for file_id in seed_ids
        if file_id in workspace.files
    }
    related_stems.update(
        _relationship_stem(path.name) for path in changed_paths
    )

    recommendations = [
        _score_record(
            record,
            workspace=workspace,
            prompt_tokens=prompt_tokens,
            prompt_phrases=prompt_phrases,
            changed_paths=changed_paths,
            direct_ids=direct_ids,
            explicit_ids=explicit_ids,
            forward_distance=forward_distances.get(record.id),
            reverse_distance=reverse_distances.get(record.id),
            related_stems=related_stems,
        )
        for record in workspace.files.values()
    ]
    return sorted(
        recommendations,
        key=lambda item: (
            _TIER_ORDER[item.tier],
            -item.score,
            workspace.files[item.file_id].repo_relative_path.lower(),
        ),
    )


def _score_record(
    record: FileRecord,
    *,
    workspace: Workspace,
    prompt_tokens: set[str],
    prompt_phrases: tuple[str, ...],
    changed_paths: set[Path],
    direct_ids: set[str],
    explicit_ids: set[str],
    forward_distance: int | None,
    reverse_distance: int | None,
    related_stems: set[str],
) -> CuratorRecommendation:
    score = 0
    weighted_reasons: list[tuple[int, str]] = []

    def add(points: int, reason: str) -> None:
        nonlocal score
        score += points
        weighted_reasons.append((abs(points), reason))

    if record.id in direct_ids:
        add(56, "explicitly added input")
    if record.id in explicit_ids and record.id not in direct_ids:
        add(28, "currently selected by the user")

    if forward_distance is not None and forward_distance > 0:
        points = max(5, 34 - (forward_distance - 1) * 7)
        add(points, f"dependency distance {forward_distance} from an explicit input")
    if reverse_distance is not None and reverse_distance > 0:
        points = max(3, 18 - (reverse_distance - 1) * 4)
        add(points, f"imports or references an explicit input at distance {reverse_distance}")

    relative_path = Path(record.repo_relative_path)
    normalized_relative = _normalized_relative_path(relative_path)
    if normalized_relative in changed_paths:
        add(32, "changed in the Git working tree")

    path_tokens = _text_tokens(record.repo_relative_path)
    path_matches = sorted(prompt_tokens & path_tokens)
    if path_matches:
        points = min(24, 6 * len(path_matches))
        add(points, f"path matches prompt terms: {', '.join(path_matches[:4])}")

    symbols = _record_symbols(record)
    symbol_matches = sorted(prompt_tokens & symbols)
    if symbol_matches:
        points = min(28, 8 * len(symbol_matches))
        add(points, f"symbols or keys match: {', '.join(symbol_matches[:4])}")

    content = record.content or ""
    phrase_matches = [phrase for phrase in prompt_phrases if phrase in content.lower()]
    if phrase_matches:
        points = min(24, 12 * len(phrase_matches))
        add(points, "contains an exact quoted prompt phrase")

    if _is_test_file(relative_path):
        stem = _relationship_stem(record.filename)
        if stem in related_stems or stem in prompt_tokens:
            add(18, "test file matches an explicit, changed, or prompt-mentioned module")
        elif any(token in record.repo_relative_path.lower() for token in prompt_tokens):
            add(10, "test path overlaps with prompt terminology")

    age_seconds = _file_age_seconds(Path(record.absolute_path))
    if age_seconds is not None:
        if age_seconds <= 24 * 3600:
            add(8, "modified within the last day")
        elif age_seconds <= 7 * 24 * 3600:
            add(5, "modified within the last week")
        elif age_seconds <= 30 * 24 * 3600:
            add(2, "modified within the last month")

    if record.metadata_only or (record.is_binary and not record.is_image):
        add(-24, "content is unavailable or metadata-only")
    elif relative_path.suffix.lower() in _ASSET_SUFFIXES and record.id not in direct_ids:
        add(-14, "asset or generated-content file")

    score = max(0, min(100, score))
    if score >= 45:
        tier = TIER_HIGH
    elif score >= 18:
        tier = TIER_POTENTIAL
    else:
        tier = TIER_LOW

    if record.id in direct_ids:
        recommended_mode = "hybrid" if record.is_large else "full"
    elif tier == TIER_HIGH:
        recommended_mode = "hybrid" if record.is_large else "full"
    elif tier == TIER_POTENTIAL:
        recommended_mode = "hybrid"
    else:
        recommended_mode = "excluded"
    if record.metadata_only or (record.is_binary and not record.is_image):
        recommended_mode = "excluded"

    reasons = tuple(
        reason
        for _weight, reason in sorted(
            weighted_reasons,
            key=lambda item: (-item[0], item[1]),
        )[:5]
    )
    if not reasons:
        reasons = ("no strong relevance signals",)

    return CuratorRecommendation(
        file_id=record.id,
        score=score,
        tier=tier,
        recommended_mode=recommended_mode,
        reasons=reasons,
    )


def _prompt_tokens(text: str) -> set[str]:
    return {
        token
        for token in _text_tokens(text)
        if len(token) >= 3 and token not in _STOP_WORDS
    }


def _prompt_phrases(text: str) -> tuple[str, ...]:
    phrases = {
        match.group(1).strip().lower()
        for match in _QUOTED_PHRASE_PATTERN.finditer(text)
        if len(match.group(1).strip()) >= 8
    }
    for line in text.splitlines():
        stripped = line.strip().lower()
        if len(stripped) >= 8 and any(
            marker in stripped for marker in ("error", "exception", "traceback", "failed")
        ):
            phrases.add(stripped[:200])
    return tuple(sorted(phrases))


def _text_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in _TOKEN_PATTERN.findall(text):
        normalized = raw.lower().replace("\\", "/")
        for part in re.split(r"[./:\-]+", normalized):
            if not part:
                continue
            tokens.add(part)
            tokens.update(piece for piece in part.split("_") if piece)
            tokens.update(
                piece.lower()
                for piece in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", part)
                if piece
            )
    return tokens


def _record_symbols(record: FileRecord) -> set[str]:
    content = record.content or ""
    suffix = Path(record.filename).suffix.lower()
    cache_key = f"{suffix}:{record.content_hash}" if record.content_hash else ""
    if cache_key and cache_key in _SYMBOL_CACHE:
        return set(_SYMBOL_CACHE[cache_key])
    symbols: set[str] = set()
    if suffix in {".py", ".pyi"}:
        try:
            tree = ast.parse(content, filename=record.absolute_path)
        except SyntaxError:
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.update(_text_tokens(node.name))
                elif isinstance(node, ast.Name):
                    symbols.update(_text_tokens(node.id))
                elif isinstance(node, ast.Attribute):
                    symbols.update(_text_tokens(node.attr))
    for match in re.finditer(
        r"(?m)^\s*[\"']?([A-Za-z_][A-Za-z0-9_.-]{2,})[\"']?\s*[:=]",
        content,
    ):
        symbols.update(_text_tokens(match.group(1)))
    if cache_key:
        _SYMBOL_CACHE[cache_key] = frozenset(symbols)
    return symbols


def _dependency_distances(
    workspace: Workspace,
    seeds: set[str],
    *,
    reverse: bool,
) -> dict[str, int]:
    adjacency: dict[str, set[str]] = {}
    for edge in workspace.dependency_graph:
        if edge.target_id is None:
            continue
        source, target = (
            (edge.target_id, edge.source_id) if reverse else (edge.source_id, edge.target_id)
        )
        adjacency.setdefault(source, set()).add(target)

    distances = {seed: 0 for seed in seeds}
    queue = deque(seeds)
    while queue:
        source = queue.popleft()
        next_distance = distances[source] + 1
        for target in adjacency.get(source, set()):
            if target in distances or target not in workspace.files:
                continue
            distances[target] = next_distance
            queue.append(target)
    return distances


def _git_changed_paths(project_root: Path) -> set[Path]:
    root = Path(project_root)
    commands = (
        ["git", "diff", "--name-only", "-z", "HEAD"],
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    )
    changed: set[Path] = set()
    for command in commands:
        try:
            result = subprocess.run(
                command,
                cwd=str(root),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode != 0:
            continue
        for raw_path in result.stdout.split(b"\0"):
            if not raw_path:
                continue
            decoded = raw_path.decode("utf-8", errors="replace")
            changed.add(_normalized_relative_path(Path(decoded)))
    return changed


def _normalized_relative_path(path: Path) -> Path:
    value = path.as_posix()
    while value.startswith("./"):
        value = value[2:]
    return Path(value)


def _is_test_file(path: Path) -> bool:
    name = path.name.lower()
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "tests" in {part.lower() for part in path.parts}
    )


def _relationship_stem(filename: str) -> str:
    stem = Path(filename).stem.lower()
    stem = re.sub(r"^(test_|tests?_)", "", stem)
    stem = re.sub(r"(_test|_tests)$", "", stem)
    return stem


def _file_age_seconds(path: Path) -> float | None:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return None
