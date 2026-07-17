from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping
import ast
import base64
import hashlib
import json
import os
import re
import sys


SCHEMA_VERSION = 1
DEFAULT_MAX_DEPENDENCY_DEPTH = 5
DEFAULT_LARGE_FILE_THRESHOLD = 256 * 1024
DEFAULT_TRUNCATION_SIZE = 40 * 1024
DEFAULT_SMALL_FUNCTION_MAX_LINES = 8
MAX_OUTLINE_VALUE_CHARS = 160
MAX_JSON_STRUCTURE_DEPTH = 6
MAX_JSON_OBJECT_KEYS = 80
MAX_JSON_SEQUENCE_ITEMS = 2
REPRESENTATION_MODES = {"outline", "hybrid"}
INCLUSION_MODES = {"full", "outline", "hybrid", "excluded"}

IGNORED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    ".env",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".hypothesis",
    "build",
    "dist",
    "site-packages",
    "node_modules",
    ".ipynb_checkpoints",
    "checkpoints",
    "artifacts",
    "output",
    "outputs",
    "tmp",
    "temp",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}

CONTENT_BLACKLIST_FILENAMES = {
    "uv.lock",
    "poetry.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
}
CONTENT_BLACKLIST_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".class",
    ".o",
    ".obj",
    ".so",
    ".dll",
    ".dylib",
    ".a",
    ".lib",
    ".exe",
    ".bin",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".rar",
}

PROJECT_MARKERS = {
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "requirements-dev.txt",
    "pytest.ini",
    "tox.ini",
    "mypy.ini",
}

COMMON_SOURCE_ROOTS = ("src", "lib", "app", "python", "source")
SYSTEM_PROMPT_FILENAME = "system_prompt.md"
LLM_TASK_TEMPLATES: dict[str, str] = {
    "code_editing": (
        "You are a careful coding assistant. Make the requested changes, keep the "
        "solution grounded in the provided repository context, and explain any "
        "important tradeoffs briefly."
    ),
    "code_review": (
        "You are a code reviewer. Focus on correctness, regressions, design risks, "
        "and missing tests. Prioritize actionable findings."
    ),
    "debugging": (
        "You are a debugging assistant. Identify likely root causes, propose a "
        "small set of checks, and recommend the most probable fix path."
    ),
    "architecture_explanation": (
        "You are an architecture explainer. Describe how the code fits together, "
        "call out boundaries, and keep the explanation practical and concrete."
    ),
    "refactor_planning": (
        "You are a refactor planner. Propose a safe sequence of steps, note "
        "dependencies, and keep the plan testable."
    ),
    "grill_me": (
        "Interview me relentlessly about every aspect of this plan until we reach a shared understanding. Walk down each branch of the design tree , resolving dependencies between decisions one-by-one. For each question, provide your recommended answer."
        "Ask the questions one at a time."
        "If a question can be answered by exploring the codebase, explore the codebase instead."
    )
}


class BuildError(RuntimeError):
    pass


@dataclass(slots=True)
class PromptTemplate:
    template_id: str
    label: str
    text: str


@dataclass(slots=True)
class PromptTemplateMode:
    mode: str = "template"
    template_id: str = "code_editing"
    custom_text: str = ""

    def resolved_text(self) -> str:
        if self.mode == "custom":
            return self.custom_text.strip()
        return LLM_TASK_TEMPLATES.get(self.template_id, LLM_TASK_TEMPLATES["code_editing"])


@dataclass(slots=True)
class PromptFields:
    llm_task: PromptTemplateMode = field(default_factory=PromptTemplateMode)
    user_prompt: str = ""


@dataclass(slots=True)
class BuildSettings:
    max_dependency_depth: int | None = DEFAULT_MAX_DEPENDENCY_DEPTH
    large_file_threshold: int = DEFAULT_LARGE_FILE_THRESHOLD
    truncation_size: int = DEFAULT_TRUNCATION_SIZE
    project_root_override: str = ""
    import_root_overrides: list[str] = field(default_factory=list)
    include_unchecked_folder_files: bool = False
    include_hidden: bool = False


@dataclass(slots=True)
class BuildRequest:
    input_paths: list[str]
    prompt: PromptFields = field(default_factory=PromptFields)
    settings: BuildSettings = field(default_factory=BuildSettings)
    file_overrides: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class FileRecord:
    id: str
    filename: str
    context_type: str
    absolute_path: str
    repo_relative_path: str
    included: bool
    inclusion_mode: str
    source_kind: str
    origin_kinds: list[str] = field(default_factory=list)
    parent_ids: list[str] = field(default_factory=list)
    size_bytes: int = 0
    line_count: int = 0
    content_hash: str = ""
    content: str | None = None
    truncation: dict | None = None
    syntax_error: str | None = None
    unreadable_reason: str | None = None
    is_binary: bool = False
    is_large: bool = False
    is_dependency: bool = False
    is_image: bool = False
    media_type: str = ""
    metadata_only: bool = False
    raw_content: bytes | None = field(default=None, repr=False)
    module_name: str = ""
    dependency_target_ids: list[str] = field(default_factory=list)
    skipped_dependencies: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class DependencyEdge:
    source_id: str
    target_id: str | None
    import_name: str
    statement: str
    reason: str = ""
    level: int = 0
    resolved_as: str = ""
    target_path: str = ""


@dataclass(slots=True)
class TreeNode:
    label: str
    kind: str
    file_id: str | None = None
    repo_relative_path: str = ""
    absolute_path: str = ""
    reused: bool = False
    skipped_reason: str = ""
    children: list["TreeNode"] = field(default_factory=list)


@dataclass(slots=True)
class Diagnostic:
    severity: str
    message: str
    file_id: str | None = None
    path: str = ""
    detail: str = ""


@dataclass(slots=True)
class Workspace:
    project_root: Path
    import_roots: list[Path]
    input_paths: list[Path]
    files: dict[str, FileRecord]
    tree_roots: list[TreeNode]
    dependency_graph: list[DependencyEdge]
    skipped_dependencies: list[dict]
    excluded_files: list[dict]
    diagnostics: list[Diagnostic]
    settings: BuildSettings

    def clone_with_overrides(self, file_overrides: Mapping[str, str]) -> "Workspace":
        cloned_files: dict[str, FileRecord] = {}
        for file_id, record in self.files.items():
            cloned = replace(record)
            cloned_files[file_id] = cloned
        for file_id, mode in file_overrides.items():
            if file_id in cloned_files:
                _apply_inclusion_mode(cloned_files[file_id], mode)
        return Workspace(
            project_root=self.project_root,
            import_roots=list(self.import_roots),
            input_paths=list(self.input_paths),
            files=cloned_files,
            tree_roots=_clone_tree_nodes(self.tree_roots),
            dependency_graph=list(self.dependency_graph),
            skipped_dependencies=list(self.skipped_dependencies),
            excluded_files=list(self.excluded_files),
            diagnostics=list(self.diagnostics),
            settings=self.settings,
        )

    def to_bundle(self, prompt: PromptFields | None = None) -> dict:
        prompt = prompt or PromptFields()
        files = []
        for record in _sorted_file_records(self.files.values()):
            keep_in_files = (
                record.source_kind == "direct_file"
                or record.is_dependency
                or record.included
                or record.metadata_only
                or (self.settings.include_unchecked_folder_files and record.source_kind == "folder_file")
            )
            if keep_in_files:
                files.append(_file_record_to_json(record))
        dependency_graph = _dependency_graph_to_json(self.dependency_graph)
        bundle = {
            "system_prompt": load_system_prompt(),
            "llm_task": prompt.llm_task.resolved_text(),
            "user_prompt": prompt.user_prompt,
            "schema_version": SCHEMA_VERSION,
            "files": files,
            "dependency_graph": dependency_graph,
        }
        validate_bundle(bundle)
        return bundle

    def bundle_json(self, prompt: PromptFields | None = None) -> str:
        return serialize_bundle(self.to_bundle(prompt))


@dataclass(slots=True)
class BuildResult:
    workspace: Workspace
    bundle: dict
    json_text: str


ProgressCallback = Callable[[str, int, int], None]
CancelCallback = Callable[[], bool]


class BundleBuilder:
    def build(
        self,
        request: BuildRequest,
        progress: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> BuildResult:
        input_paths = [Path(path).expanduser().resolve() for path in request.input_paths]
        if not input_paths:
            raise BuildError("At least one file or folder must be provided.")

        settings = request.settings
        project_root = _detect_project_root(input_paths, settings.project_root_override)
        import_roots = _detect_import_roots(project_root, settings.import_root_overrides)

        workspace = Workspace(
            project_root=project_root,
            import_roots=import_roots,
            input_paths=input_paths,
            files={},
            tree_roots=[],
            dependency_graph=[],
            skipped_dependencies=[],
            excluded_files=[],
            diagnostics=[],
            settings=settings,
        )
        index = _build_module_index(project_root, import_roots, settings, progress, should_cancel)
        file_cache: dict[Path, FileRecord] = {}
        tree_roots: list[TreeNode] = []

        for position, input_path in enumerate(input_paths, start=1):
            _check_cancel(should_cancel)
            if progress:
                progress(f"Scanning input {position}/{len(input_paths)}", position, len(input_paths))
            if input_path.is_dir():
                folder_node = TreeNode(
                    label=input_path.name or input_path.as_posix(),
                    kind="folder",
                    repo_relative_path=_relative_path(input_path, project_root),
                    absolute_path=_path_to_json(input_path),
                )
                children = _scan_folder(
                    input_path,
                    project_root,
                    import_roots,
                    index,
                    settings,
                    workspace,
                    file_cache,
                    progress,
                    should_cancel,
                    folder_node,
                )
                folder_node.children.extend(children)
                tree_roots.append(folder_node)
            else:
                record, node = _scan_file_root(
                    input_path,
                    project_root,
                    import_roots,
                    index,
                    settings,
                    workspace,
                    file_cache,
                    progress,
                    should_cancel,
                )
                if record is not None and node is not None:
                    tree_roots.append(node)

        workspace.tree_roots = tree_roots
        workspace.files = {record.id: record for record in sorted(file_cache.values(), key=lambda item: item.id)}
        for file_id, mode in request.file_overrides.items():
            if file_id in workspace.files:
                _apply_inclusion_mode(workspace.files[file_id], mode)
        bundle = workspace.to_bundle(request.prompt)
        json_text = serialize_bundle(bundle)
        return BuildResult(workspace=workspace, bundle=bundle, json_text=json_text)


def build_context_structure(
    request: BuildRequest,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> BuildResult:
    return BundleBuilder().build(request, progress=progress, should_cancel=should_cancel)


def build_prompt_bundle(
    request: BuildRequest,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> BuildResult:
    return build_context_structure(request, progress=progress, should_cancel=should_cancel)


def load_system_prompt() -> str:
    prompt_path = Path(__file__).resolve().parent.parent.parent / SYSTEM_PROMPT_FILENAME
    try:
        prompt_text = prompt_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise BuildError(f"Unable to read {SYSTEM_PROMPT_FILENAME}: {exc}") from exc

    if not prompt_text:
        raise BuildError(f"{SYSTEM_PROMPT_FILENAME} is empty.")
    return prompt_text


def serialize_bundle(bundle: dict) -> str:
    validate_bundle(bundle)
    return json.dumps(bundle, indent=2, ensure_ascii=False)


def validate_bundle(bundle: dict) -> None:
    required = {
        "system_prompt",
        "llm_task",
        "user_prompt",
        "schema_version",
        "files",
        "dependency_graph",
    }
    missing = required.difference(bundle.keys())
    if missing:
        raise BuildError(f"Bundle is missing required keys: {sorted(missing)}")
    if bundle["schema_version"] != SCHEMA_VERSION:
        raise BuildError(f"Unsupported schema version: {bundle['schema_version']}")
    if not isinstance(bundle["files"], list):
        raise BuildError("files must be a list")
    if not isinstance(bundle["dependency_graph"], list):
        raise BuildError("dependency_graph must be a list")
    json.dumps(bundle, ensure_ascii=False)


def render_record_content(record: FileRecord) -> str | None:
    """Return the exact content representation that will be serialized for a file."""
    return _render_content(record)


def set_record_inclusion_mode(record: FileRecord, mode: str) -> None:
    """Apply a UI/session inclusion mode to a file record."""
    _apply_inclusion_mode(record, mode)


def _file_record_to_json(record: FileRecord) -> dict:
    if record.metadata_only:
        return {
            "filename": record.filename,
            "repo_relative_path": record.repo_relative_path,
        }

    rendered_content = _render_content(record)
    result = {
        "id": record.id,
        "context_type": record.context_type,
        "repo_relative_path": record.repo_relative_path,
        "included": record.included,
        "content": rendered_content,
    }
    if record.is_image:
        result["content_encoding"] = "base64"
        result["media_type"] = record.media_type
    if record.truncation is not None:
        result["truncation"] = dict(record.truncation)
    return result


def _dependency_graph_to_json(edges: Iterable[DependencyEdge]) -> list[dict]:
    grouped: dict[str, set[str]] = {}
    for edge in edges:
        if edge.target_id is None:
            continue
        grouped.setdefault(edge.source_id, set()).add(edge.target_id)
    output = []
    for source_id in sorted(grouped):
        output.append(
            {
                "source_id": source_id,
                "includes": sorted(grouped[source_id]),
            }
        )
    return output


def _path_to_json(path: Path) -> str:
    return Path(path).resolve().as_posix()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _sorted_file_records(records: Iterable[FileRecord]) -> list[FileRecord]:
    return sorted(records, key=lambda record: (record.repo_relative_path, record.absolute_path, record.id))


def _included_content_bytes(record: FileRecord) -> int:
    rendered = _render_content(record)
    if rendered is None:
        return 0
    return len(rendered.encode("utf-8"))


def _clone_tree_nodes(nodes: Iterable[TreeNode]) -> list[TreeNode]:
    cloned: list[TreeNode] = []
    for node in nodes:
        cloned.append(
            TreeNode(
                label=node.label,
                kind=node.kind,
                file_id=node.file_id,
                repo_relative_path=node.repo_relative_path,
                absolute_path=node.absolute_path,
                reused=node.reused,
                skipped_reason=node.skipped_reason,
                children=_clone_tree_nodes(node.children),
            )
        )
    return cloned


def _apply_inclusion_mode(record: FileRecord, mode: str) -> None:
    normalized = _normalize_inclusion_mode(mode)
    record.inclusion_mode = normalized
    record.included = normalized != "excluded"
    if normalized in REPRESENTATION_MODES and record.content is not None:
        record.truncation = _make_truncation_metadata(
            mode=normalized,
            original_bytes=record.size_bytes,
            limit_bytes=DEFAULT_TRUNCATION_SIZE,
        )
    elif normalized == "full":
        record.truncation = None


def _normalize_inclusion_mode(mode: str) -> str:
    normalized = mode.lower().strip()
    if normalized == "truncated":
        return "hybrid"
    if normalized in INCLUSION_MODES:
        return normalized
    if normalized in {"include", "included", "true", "1", "yes"}:
        return "full"
    if normalized in {"summary", "summarized", "compact", "smart", "adaptive"}:
        return "hybrid"
    return "excluded"


def _make_truncation_metadata(
    mode: str,
    original_bytes: int,
    limit_bytes: int,
    *,
    rendered_bytes: int | None = None,
    strategy: str = "adaptive",
) -> dict:
    metadata = {
        "mode": mode,
        "strategy": strategy,
        "original_bytes": original_bytes,
        "limit_bytes": limit_bytes,
    }
    if rendered_bytes is not None:
        metadata["rendered_bytes"] = rendered_bytes
        metadata["kept_bytes"] = rendered_bytes
    return metadata


def _check_cancel(should_cancel: CancelCallback | None) -> None:
    if should_cancel and should_cancel():
        raise BuildError("Operation cancelled.")


def _detect_project_root(input_paths: list[Path], override: str) -> Path:
    if override:
        return Path(override).expanduser().resolve()

    candidates: list[tuple[int, int, Path]] = []
    for path in input_paths:
        current = path if path.is_dir() else path.parent
        for distance, ancestor in enumerate([current, *current.parents]):
            if (ancestor / ".git").exists():
                candidates.append((0, distance, ancestor))
                break
        for distance, ancestor in enumerate([current, *current.parents]):
            if any((ancestor / marker).exists() for marker in PROJECT_MARKERS):
                candidates.append((1, distance, ancestor))
                break
        for distance, ancestor in enumerate([current, *current.parents]):
            if any((ancestor / root).exists() for root in COMMON_SOURCE_ROOTS):
                candidates.append((2, distance, ancestor))
                break

    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1], len(item[2].parts)))
        return candidates[0][2].resolve()

    if len(input_paths) == 1:
        return (input_paths[0] if input_paths[0].is_dir() else input_paths[0].parent).resolve()

    common = _common_ancestor(input_paths)
    return common if common is not None else input_paths[0].parent.resolve()


def _detect_import_roots(project_root: Path, overrides: list[str]) -> list[Path]:
    roots: list[Path] = [project_root.resolve()]
    for name in COMMON_SOURCE_ROOTS:
        candidate = project_root / name
        if candidate.exists() and candidate.is_dir():
            roots.append(candidate.resolve())
    for override in overrides:
        candidate = Path(override).expanduser().resolve()
        if candidate.exists() and candidate.is_dir():
            roots.append(candidate)
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = root.as_posix()
        if key not in seen:
            unique.append(root)
            seen.add(key)
    unique.sort(key=lambda item: (len(item.parts), item.as_posix()))
    return unique


def _common_ancestor(paths: Iterable[Path]) -> Path | None:
    resolved = [path.resolve() for path in paths]
    if not resolved:
        return None
    common_parts = list(resolved[0].parts)
    for path in resolved[1:]:
        new_parts: list[str] = []
        for left, right in zip(common_parts, path.parts):
            if left != right:
                break
            new_parts.append(left)
        common_parts = new_parts
        if not common_parts:
            return None
    return Path(*common_parts)


def _build_module_index(
    project_root: Path,
    import_roots: list[Path],
    settings: BuildSettings,
    progress: ProgressCallback | None,
    should_cancel: CancelCallback | None,
) -> dict[str, Path]:
    index: dict[str, Path] = {}
    python_files: list[Path] = []
    for root in import_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_dir():
                if _ignored_directory(path):
                    continue
                continue
            if path.suffix.lower() in {".py", ".pyi"}:
                python_files.append(path.resolve())
    python_files = sorted({path.as_posix(): path for path in python_files}.values(), key=lambda item: item.as_posix())

    total = len(python_files)
    for position, path in enumerate(python_files, start=1):
        _check_cancel(should_cancel)
        if progress and total:
            progress(f"Indexing Python files {position}/{total}", position, total)
        if _ignored_path(path, settings.include_hidden):
            continue
        module_name = _module_name_for_path(path, import_roots)
        if not module_name:
            continue
        existing = index.get(module_name)
        if existing is None or len(path.parts) < len(existing.parts):
            index[module_name] = path
    return index


def _scan_folder(
    folder: Path,
    project_root: Path,
    import_roots: list[Path],
    module_index: Mapping[str, Path],
    settings: BuildSettings,
    workspace: Workspace,
    file_cache: dict[Path, FileRecord],
    progress: ProgressCallback | None,
    should_cancel: CancelCallback | None,
    parent_node: TreeNode,
) -> list[TreeNode]:
    children: list[TreeNode] = []
    candidates = sorted(_iter_folder_files(folder, settings.include_hidden), key=lambda item: item.as_posix())
    total = len(candidates)
    for position, path in enumerate(candidates, start=1):
        _check_cancel(should_cancel)
        if progress and total:
            progress(f"Scanning folder files {position}/{total}", position, total)
        record, node = _ensure_record(
            path,
            project_root,
            import_roots,
            module_index,
            settings,
            workspace,
            file_cache,
            source_kind="folder_file",
            context_type="file_from_folder",
            parent_ids=[parent_node.file_id] if parent_node.file_id else [],
            origin_kinds=["folder_file"],
            is_dependency=False,
        )
        if record is None or node is None:
            continue
        children.append(node)
        if _is_python_file(path):
            _expand_dependencies(
                record,
                node,
                project_root,
                import_roots,
                module_index,
                settings,
                workspace,
                file_cache,
                progress,
                should_cancel,
                root_origin_kind="folder_file",
                current_depth=0,
                ancestry={record.absolute_path},
            )
    return children


def _scan_file_root(
    path: Path,
    project_root: Path,
    import_roots: list[Path],
    module_index: Mapping[str, Path],
    settings: BuildSettings,
    workspace: Workspace,
    file_cache: dict[Path, FileRecord],
    progress: ProgressCallback | None,
    should_cancel: CancelCallback | None,
) -> tuple[FileRecord | None, TreeNode | None]:
    if path.exists() and path.is_file():
        record, node = _ensure_record(
            path,
            project_root,
            import_roots,
            module_index,
            settings,
            workspace,
            file_cache,
            source_kind="direct_file",
            context_type="file_from_user",
            parent_ids=[],
            origin_kinds=["direct_file"],
            is_dependency=False,
        )
        if record is None or node is None:
            return None, None
        if _is_python_file(path):
            _expand_dependencies(
                record,
                node,
                project_root,
                import_roots,
                module_index,
                settings,
                workspace,
                file_cache,
                progress,
                should_cancel,
                root_origin_kind="direct_file",
                current_depth=0,
                ancestry={record.absolute_path},
            )
        return record, node
    return None, None


def _ensure_record(
    path: Path,
    project_root: Path,
    import_roots: list[Path],
    module_index: Mapping[str, Path],
    settings: BuildSettings,
    workspace: Workspace,
    file_cache: dict[Path, FileRecord],
    source_kind: str,
    context_type: str,
    parent_ids: list[str],
    origin_kinds: list[str],
    is_dependency: bool,
) -> tuple[FileRecord | None, TreeNode | None]:
    path = path.resolve()
    if source_kind != "direct_file" and _ignored_path(path, settings.include_hidden):
        return None, TreeNode(label=path.name, kind="ignored", file_id=None, repo_relative_path=_relative_path(path, project_root), absolute_path=_path_to_json(path), skipped_reason="ignored by path rules")

    existing = file_cache.get(path)
    if existing is not None:
        for kind in origin_kinds:
            if kind not in existing.origin_kinds:
                existing.origin_kinds.append(kind)
        for parent_id in parent_ids:
            if parent_id not in existing.parent_ids:
                existing.parent_ids.append(parent_id)
        if (
            context_type == "file_from_user"
            or source_kind == "direct_file"
            or existing.context_type == "file_from_user"
            or existing.source_kind == "direct_file"
        ):
            existing.context_type = "file_from_user"
            existing.source_kind = "direct_file"
            existing.is_dependency = False
        else:
            existing.is_dependency = existing.is_dependency or is_dependency
        node = _make_tree_node(existing, reused=True)
        return existing, node

    metadata_only = _is_metadata_only_candidate(path)
    if metadata_only:
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = 0
        content = None
        raw_bytes = b""
        is_binary = True
        is_large = False
        truncation = None
        unreadable_reason = "content omitted by blacklist"
        syntax_error = None
    else:
        loaded = _read_file(path, settings.large_file_threshold, settings.truncation_size)
        if loaded is None:
            return None, TreeNode(label=path.name, kind="skipped", file_id=None, repo_relative_path=_relative_path(path, project_root), absolute_path=_path_to_json(path), skipped_reason="unreadable")
        content, raw_bytes, is_binary, is_large, truncation, unreadable_reason, syntax_error = loaded
        size_bytes = len(raw_bytes)

    is_image = _is_image_file(path)
    repo_relative_path = _relative_path(path, project_root)
    file_id = repo_relative_path
    included, inclusion_mode = _default_inclusion_state(context_type, is_large, is_binary, is_dependency)
    module_name = _module_name_for_path(path, import_roots)
    record = FileRecord(
        id=file_id,
        filename=path.name,
        context_type=context_type,
        absolute_path=_path_to_json(path),
        repo_relative_path=repo_relative_path,
        included=included,
        inclusion_mode=inclusion_mode,
        source_kind=source_kind,
        origin_kinds=list(dict.fromkeys(origin_kinds)),
        parent_ids=list(dict.fromkeys(parent_ids)),
        size_bytes=size_bytes,
        line_count=_line_count(content),
        content_hash=hashlib.sha256(raw_bytes).hexdigest(),
        content=content,
        truncation=truncation,
        syntax_error=syntax_error,
        unreadable_reason=unreadable_reason,
        is_binary=is_binary,
        is_large=is_large,
        is_dependency=is_dependency,
        is_image=is_image,
        media_type=IMAGE_MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream") if is_image else "",
        metadata_only=metadata_only,
        raw_content=raw_bytes if is_image else None,
        module_name=module_name,
    )
    if is_binary and unreadable_reason is None:
        record.unreadable_reason = "binary file"
    file_cache[path] = record
    node = _make_tree_node(record, reused=False)
    if is_large and not included:
        workspace.excluded_files.append(
            {
                "id": record.id,
                "reason": "large_file",
                "context_type": record.context_type,
                "absolute_path": record.absolute_path,
                "repo_relative_path": record.repo_relative_path,
                "size": record.size_bytes,
            }
        )
    elif is_binary and not included:
        workspace.excluded_files.append(
            {
                "id": record.id,
                "reason": "binary_file",
                "context_type": record.context_type,
                "absolute_path": record.absolute_path,
                "repo_relative_path": record.repo_relative_path,
                "size": record.size_bytes,
            }
        )
    return record, node


def _expand_dependencies(
    record: FileRecord,
    node: TreeNode,
    project_root: Path,
    import_roots: list[Path],
    module_index: Mapping[str, Path],
    settings: BuildSettings,
    workspace: Workspace,
    file_cache: dict[Path, FileRecord],
    progress: ProgressCallback | None,
    should_cancel: CancelCallback | None,
    root_origin_kind: str,
    current_depth: int,
    ancestry: set[str],
) -> None:
    if not _is_python_file(Path(record.absolute_path)):
        return
    if settings.max_dependency_depth is not None and current_depth >= settings.max_dependency_depth:
        return

    cached_edges = [edge for edge in workspace.dependency_graph if edge.source_id == record.id]
    if record.dependency_target_ids and cached_edges:
        _expand_cached_dependency_nodes(
            record,
            node,
            project_root,
            import_roots,
            settings,
            workspace,
            file_cache,
            progress,
            should_cancel,
            root_origin_kind,
            current_depth,
            ancestry,
            cached_edges,
        )
        return

    dependency_entries = _parse_imports(Path(record.absolute_path))

    for imported_name, statement, level, is_from_import, base_module in dependency_entries:
        _check_cancel(should_cancel)
        resolved = _resolve_import(
            imported_name,
            statement,
            level,
            is_from_import,
            base_module,
            record,
            module_index,
            project_root,
        )
        if resolved is None:
            reason = "stdlib" if _is_stdlib_module(imported_name) else "unresolved_or_external"
            skipped = {
                "source_id": record.id,
                "import_name": imported_name,
                "statement": statement,
                "reason": reason,
                "detail": "No repo-local module matched the import.",
            }
            record.skipped_dependencies.append(skipped)
            workspace.skipped_dependencies.append(skipped)
            node.children.append(
                TreeNode(
                    label=imported_name,
                    kind="skipped",
                    skipped_reason=reason,
                )
            )
            workspace.diagnostics.append(
                Diagnostic(
                    severity="warning",
                    message=f"Skipped import {imported_name!r} from {record.repo_relative_path}: {reason}",
                    file_id=record.id,
                    path=record.absolute_path,
                    detail=statement,
                )
            )
            continue

        target_path = resolved.resolve()
        if target_path in ancestry:
            edge = DependencyEdge(
                source_id=record.id,
                target_id=_relative_id_for_path(target_path, project_root),
                import_name=imported_name,
                statement=statement,
                reason="circular",
                level=level,
                resolved_as="cycle",
                target_path=_path_to_json(target_path),
            )
            workspace.dependency_graph.append(edge)
            node.children.append(
                TreeNode(
                    label=_relative_id_for_path(target_path, project_root),
                    kind="dependency",
                    file_id=edge.target_id,
                    repo_relative_path=_relative_path(target_path, project_root),
                    absolute_path=_path_to_json(target_path),
                    reused=True,
                    skipped_reason="circular_import",
                )
            )
            continue

        target_record, target_node = _ensure_record(
            target_path,
            project_root,
            import_roots,
            module_index,
            settings,
            workspace,
            file_cache,
            source_kind="dependency_file" if root_origin_kind == "direct_file" else "file_from_folder_dependency",
            context_type="dependency_file" if root_origin_kind == "direct_file" else "file_from_folder_dependency",
            parent_ids=[record.id],
            origin_kinds=[("dependency_file" if root_origin_kind == "direct_file" else "file_from_folder_dependency")],
            is_dependency=True,
        )
        if target_record is None or target_node is None:
            continue
        if record.id not in target_record.parent_ids:
            target_record.parent_ids.append(record.id)
        if target_record.id not in record.dependency_target_ids:
            record.dependency_target_ids.append(target_record.id)
        edge = DependencyEdge(
            source_id=record.id,
            target_id=target_record.id,
            import_name=imported_name,
            statement=statement,
            reason="",
            level=level,
            resolved_as="local_file",
            target_path=target_record.absolute_path,
        )
        workspace.dependency_graph.append(edge)
        node.children.append(target_node)
        if target_record.absolute_path not in ancestry:
            target_ancestry = set(ancestry)
            target_ancestry.add(target_record.absolute_path)
            _expand_dependencies(
                target_record,
                target_node,
                project_root,
                import_roots,
                module_index,
                settings,
                workspace,
                file_cache,
                progress,
                should_cancel,
                root_origin_kind=root_origin_kind,
                current_depth=current_depth + 1,
                ancestry=target_ancestry,
            )


def _expand_cached_dependency_nodes(
    record: FileRecord,
    node: TreeNode,
    project_root: Path,
    import_roots: list[Path],
    settings: BuildSettings,
    workspace: Workspace,
    file_cache: dict[Path, FileRecord],
    progress: ProgressCallback | None,
    should_cancel: CancelCallback | None,
    root_origin_kind: str,
    current_depth: int,
    ancestry: set[str],
    cached_edges: list[DependencyEdge],
) -> None:
    for edge in cached_edges:
        _check_cancel(should_cancel)
        if edge.target_id is None:
            continue
        target_record = next((item for item in file_cache.values() if item.id == edge.target_id), None)
        if target_record is None:
            continue
        reused_node = _make_tree_node(target_record, reused=True)
        node.children.append(reused_node)
        if settings.max_dependency_depth is not None and current_depth >= settings.max_dependency_depth:
            continue
        if target_record.absolute_path in ancestry:
            continue
        next_ancestry = set(ancestry)
        next_ancestry.add(target_record.absolute_path)
        _expand_dependencies(
            target_record,
            reused_node,
            project_root,
            import_roots,
            module_index={},
            settings=settings,
            workspace=workspace,
            file_cache=file_cache,
            progress=progress,
            should_cancel=should_cancel,
            root_origin_kind=root_origin_kind,
            current_depth=current_depth + 1,
            ancestry=next_ancestry,
        )


def _parse_imports(path: Path) -> list[tuple[str, str, int, bool, str]]:
    try:
        source = path.read_text(encoding="utf-8")
    except Exception:
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    results: list[tuple[str, str, int, bool, str]] = []
    for node in ast.walk(tree):
        statement = _safe_unparse(node)
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append((alias.name, statement, 0, False, ""))
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            for alias in node.names:
                imported_name = alias.name if base == "" else f"{base}.{alias.name}" if alias.name != "*" else base
                results.append((imported_name, statement, node.level or 0, True, base))
    return results


def _resolve_import(
    imported_name: str,
    statement: str,
    level: int,
    is_from_import: bool,
    base_module: str,
    record: FileRecord,
    module_index: Mapping[str, Path],
    project_root: Path,
) -> Path | None:
    candidates: list[str] = []
    if is_from_import:
        base = _relative_base_module(record.module_name, level, Path(record.absolute_path)) if level > 0 else ""
        if imported_name:
            candidates.append(_qualify_relative_module(base, imported_name))
            if base_module:
                candidates.append(_qualify_relative_module(base, base_module))
        if base_module:
            absolute_base = _qualify_relative_module(base, base_module)
            if absolute_base:
                candidates.append(absolute_base)
        if not candidates and base_module:
            candidates.append(_qualify_relative_module(base, base_module))
    else:
        candidates.append(imported_name)

    for candidate in candidates:
        if not candidate:
            continue
        resolved = module_index.get(candidate)
        if resolved is not None:
            return resolved

    if not is_from_import:
        package_candidate = module_index.get(imported_name.rsplit(".", 1)[0] if "." in imported_name else imported_name)
        if package_candidate is not None:
            return package_candidate
    return None


def _relative_base_module(module_name: str, level: int, path: Path) -> str:
    if not module_name:
        return ""
    parts = module_name.split(".")
    is_init_file = path.name in {"__init__.py", "__init__.pyi"}
    package_parts = parts if is_init_file else parts[:-1]
    if level <= 1:
        return ".".join(package_parts)
    drop = level - 1
    if len(package_parts) <= drop:
        return ""
    return ".".join(package_parts[:-drop])


def _qualify_relative_module(base: str, name: str) -> str:
    if not base:
        return name
    if not name:
        return base
    return f"{base}.{name}"


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        if isinstance(node, ast.Import):
            return "import " + ", ".join(alias.name for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            dots = "." * (node.level or 0)
            module = node.module or ""
            return f"from {dots}{module} import " + ", ".join(alias.name for alias in node.names)
        return type(node).__name__


def _module_name_for_path(path: Path, import_roots: list[Path]) -> str:
    candidates = [root for root in import_roots if _is_ancestor(root, path)]
    if not candidates:
        return ""
    root = sorted(candidates, key=lambda item: len(item.parts), reverse=True)[0]
    relative = path.resolve().relative_to(root.resolve())
    parts = list(relative.parts)
    if not parts:
        return ""
    if parts[-1] in {"__init__.py", "__init__.pyi"}:
        parts = parts[:-1]
    else:
        parts[-1] = Path(parts[-1]).stem
    parts = [part for part in parts if part]
    return ".".join(parts)


def _is_ancestor(ancestor: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(ancestor.resolve())
        return True
    except ValueError:
        return False


def _iter_folder_files(folder: Path, include_hidden: bool) -> Iterator[Path]:
    for root, dirs, files in os.walk(folder):
        root_path = Path(root)
        dirs[:] = [name for name in dirs if not _ignored_directory(root_path / name)]
        for name in sorted(files):
            path = root_path / name
            if _ignored_path(path, include_hidden):
                continue
            if _is_file_candidate(path):
                yield path.resolve()


def _ignored_directory(path: Path) -> bool:
    return path.name in IGNORED_DIR_NAMES or path.name.startswith(".venv")


def _ignored_path(path: Path, include_hidden: bool) -> bool:
    if not include_hidden and any(part.startswith(".") and part not in {".", ".."} for part in path.parts if part not in {path.anchor, path.drive}):
        if path.name not in {".gitignore", ".dockerignore"}:
            return True
    return any(part in IGNORED_DIR_NAMES for part in path.parts)


def _is_file_candidate(path: Path) -> bool:
    return path.is_file()


def _is_image_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def _is_metadata_only_candidate(path: Path) -> bool:
    return (
        path.name.lower() in CONTENT_BLACKLIST_FILENAMES
        or path.suffix.lower() in CONTENT_BLACKLIST_EXTENSIONS
    )


def _is_python_file(path: Path) -> bool:
    return path.suffix.lower() in {".py", ".pyi"}


def _read_file(path: Path, large_threshold: int, truncation_size: int) -> tuple[str, bytes, bool, bool, dict | None, str | None, str | None] | None:
    try:
        raw = path.read_bytes()
    except Exception as exc:
        return None
    is_binary = b"\0" in raw[:4096]
    if is_binary:
        return "", raw, True, False, None, "binary file", None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    is_large = len(raw) > large_threshold
    truncation = None
    if is_large:
        truncation = _make_truncation_metadata(
            mode="hybrid",
            original_bytes=len(raw),
            limit_bytes=truncation_size,
        )
    return text, raw, False, is_large, truncation, None, None


def _default_inclusion_state(context_type: str, is_large: bool, is_binary: bool, is_dependency: bool) -> tuple[bool, str]:
    if is_binary:
        return False, "excluded"
    if is_large:
        return True, "hybrid"
    if is_dependency:
        return True, "full"
    return True, "full"


def _make_tree_node(record: FileRecord, reused: bool) -> TreeNode:
    label = record.repo_relative_path
    if reused:
        label = f"{label} (reused)"
    if record.is_large and not record.included:
        label = f"{label} (large)"
    if record.is_binary:
        label = f"{label} (binary)"
    return TreeNode(
        label=label,
        kind="dependency" if record.is_dependency else "file",
        file_id=record.id,
        repo_relative_path=record.repo_relative_path,
        absolute_path=record.absolute_path,
        reused=reused,
    )


def _render_content(record: FileRecord) -> str | None:
    if not record.included:
        return None
    if record.is_image:
        if record.raw_content is None:
            return None
        return base64.b64encode(record.raw_content).decode("ascii")
    if record.content is None:
        return None

    mode = _normalize_inclusion_mode(record.inclusion_mode)
    if mode in REPRESENTATION_MODES:
        limit = DEFAULT_TRUNCATION_SIZE
        if record.truncation and isinstance(record.truncation.get("limit_bytes"), int):
            limit = int(record.truncation["limit_bytes"])
        rendered, strategy = _render_adaptive_representation(record, mode, limit)
        record.inclusion_mode = mode
        record.truncation = _make_truncation_metadata(
            mode=mode,
            original_bytes=record.size_bytes,
            limit_bytes=limit,
            rendered_bytes=len(rendered.encode("utf-8")),
            strategy=strategy,
        )
        return rendered

    return record.content


def _render_adaptive_representation(record: FileRecord, mode: str, limit: int) -> tuple[str, str]:
    path = Path(record.absolute_path)
    suffix = path.suffix.lower()
    if suffix in {".py", ".pyi"}:
        return _render_python_representation(record, mode), f"python_{mode}_ast"
    if suffix in {".md", ".mdx", ".rst"}:
        return _render_markdown_outline(record, limit), "markdown_headings"
    if suffix == ".json":
        return _render_json_structure(record, limit), "json_structure"
    if suffix in {".yaml", ".yml"}:
        return _render_yaml_key_outline(record, limit), "yaml_keys"
    return _render_byte_limited_text(record.content or "", limit), "byte_truncate"


def _representation_header(record: FileRecord, mode: str, strategy: str) -> list[str]:
    return [
        f"# {mode.title()} representation generated because this file is large or was requested in compact mode.",
        "# Implementation bodies are omitted except for small functions in hybrid mode.",
        f"# Strategy: {strategy}",
        f"# Source: {record.repo_relative_path}",
        f"# Original bytes: {record.size_bytes}",
        f"# Original lines: {record.line_count}",
        "",
    ]


def _render_python_representation(record: FileRecord, mode: str) -> str:
    source = record.content or ""
    try:
        tree = ast.parse(source, filename=record.absolute_path)
    except SyntaxError as exc:
        header = _representation_header(record, mode, "python_ast_failed")
        header.extend(
            [
                f"# SyntaxError while generating outline: {exc}",
                "# Falling back to byte-limited content.",
                "",
                _render_byte_limited_text(source, DEFAULT_TRUNCATION_SIZE),
            ]
        )
        return "\n".join(header).rstrip() + "\n"

    lines = _representation_header(record, mode, f"python_{mode}_ast")
    module_docstring = ast.get_docstring(tree)
    if module_docstring:
        lines.extend(["# Module docstring", *_render_docstring_lines(module_docstring), ""])

    imports = [_safe_unparse(node) for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    if imports:
        lines.append("# Imports")
        lines.extend(imports)
        lines.append("")

    constants = [
        rendered
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for rendered in [_render_assignment_outline(node)]
        if rendered
    ]
    if constants:
        lines.append("# Module constants and top-level assignments")
        lines.extend(constants)
        lines.append("")

    public_symbols = [
        node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    ]
    internal_symbols = [
        node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("_")
    ]

    if public_symbols:
        lines.extend(["# Public API", ""])
        lines.extend(_render_python_symbols(public_symbols, source, mode))
    if internal_symbols:
        lines.extend(["# Internal helpers", ""])
        lines.extend(_render_python_symbols(internal_symbols, source, mode))

    return "\n".join(lines).rstrip() + "\n"


def _render_python_symbols(nodes: list[ast.AST], source: str, mode: str) -> list[str]:
    lines: list[str] = []
    for node in nodes:
        if isinstance(node, ast.ClassDef):
            lines.extend(_render_class_outline(node, source, mode))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines.extend(_render_function_outline(node, source, mode, indent=""))
        lines.append("")
    return lines


def _render_class_outline(node: ast.ClassDef, source: str, mode: str) -> list[str]:
    lines: list[str] = []
    bases = [_safe_unparse(base) for base in node.bases]
    base_text = f"({', '.join(bases)})" if bases else ""
    lines.append(f"# Lines: {node.lineno}-{getattr(node, 'end_lineno', node.lineno)}")
    if bases:
        lines.append(f"# Bases: {', '.join(bases)}")
    for decorator in node.decorator_list:
        lines.append(f"@{_safe_unparse(decorator)}")
    lines.append(f"class {node.name}{base_text}:")

    docstring = ast.get_docstring(node)
    body_lines: list[str] = []
    if docstring:
        body_lines.extend(_render_docstring_lines(docstring, indent="    "))

    fields = [_render_assignment_outline(child, indent="    ") for child in node.body if isinstance(child, (ast.Assign, ast.AnnAssign))]
    fields = [field for field in fields if field]
    if fields:
        body_lines.append("    # Fields")
        body_lines.extend(fields)

    nested_classes = [child for child in node.body if isinstance(child, ast.ClassDef)]
    methods = [child for child in node.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if methods:
        body_lines.append("    # Methods")
        for method in methods:
            body_lines.extend(_render_function_outline(method, source, mode, indent="    "))
            body_lines.append("")
    if nested_classes:
        body_lines.append("    # Nested classes")
        for nested in nested_classes:
            body_lines.extend(_indent_lines(_render_class_outline(nested, source, mode), "    "))
            body_lines.append("")

    if not body_lines:
        body_lines.append("    ...")
    while body_lines and body_lines[-1] == "":
        body_lines.pop()
    lines.extend(body_lines)
    return lines


def _render_function_outline(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    source: str,
    mode: str,
    *,
    indent: str,
) -> list[str]:
    if mode == "hybrid" and _is_small_function(node):
        source_segment = ast.get_source_segment(source, node)
        if source_segment:
            return _indent_lines(_dedent_ast_source_segment(source_segment, node.col_offset), indent)

    lines: list[str] = []
    lines.append(f"{indent}# Lines: {node.lineno}-{getattr(node, 'end_lineno', node.lineno)}")
    for decorator in node.decorator_list:
        lines.append(f"{indent}@{_safe_unparse(decorator)}")
    lines.append(f"{indent}{_function_header(node)}")
    docstring = ast.get_docstring(node)
    if docstring:
        lines.extend(_render_docstring_lines(docstring, indent=f"{indent}    "))
    lines.append(f"{indent}    ...")
    return lines


def _function_header(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    args = _safe_unparse(node.args)
    returns = f" -> {_safe_unparse(node.returns)}" if node.returns is not None else ""
    return f"{prefix} {node.name}({args}){returns}:"


def _is_small_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    end_lineno = getattr(node, "end_lineno", node.lineno)
    line_span = max(1, end_lineno - node.lineno + 1)
    if line_span > DEFAULT_SMALL_FUNCTION_MAX_LINES:
        return False
    return not any(isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for child in ast.walk(node) if child is not node)


def _dedent_ast_source_segment(segment: str, col_offset: int) -> list[str]:
    lines = segment.rstrip().splitlines()
    if col_offset <= 0:
        return lines
    prefix = " " * col_offset
    return [line[col_offset:] if line.startswith(prefix) else line for line in lines]


def _render_docstring_lines(docstring: str, indent: str = "") -> list[str]:
    stripped = docstring.strip()
    if not stripped:
        return []
    escaped = stripped.replace('"""', '\"\"\"')
    if "\n" not in escaped:
        return [f'{indent}"""{escaped}"""']
    return [f'{indent}"""', *[f"{indent}{line}" for line in escaped.splitlines()], f'{indent}"""']


def _render_assignment_outline(node: ast.Assign | ast.AnnAssign, indent: str = "") -> str:
    if isinstance(node, ast.AnnAssign):
        target = _safe_unparse(node.target)
        annotation = _safe_unparse(node.annotation)
        if node.value is None:
            return f"{indent}{target}: {annotation}"
        return f"{indent}{target}: {annotation} = {_summarize_ast_value(node.value)}"

    targets = [_safe_unparse(target) for target in node.targets]
    if not targets:
        return ""
    return f"{indent}{' = '.join(targets)} = {_summarize_ast_value(node.value)}"


def _summarize_ast_value(value: ast.AST) -> str:
    if isinstance(value, ast.Dict):
        keys = []
        for key in value.keys[:8]:
            keys.append(_safe_unparse(key) if key is not None else "**")
        suffix = ", ..." if len(value.keys) > 8 else ""
        return "{" + ", ".join(f"{key}: ..." for key in keys) + suffix + "}"
    if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
        open_char, close_char = ("[", "]") if isinstance(value, ast.List) else ("(", ")") if isinstance(value, ast.Tuple) else ("{", "}")
        elements = [_safe_unparse(element) for element in value.elts[:8]]
        suffix = ", ..." if len(value.elts) > 8 else ""
        return open_char + ", ".join(elements) + suffix + close_char
    rendered = _safe_unparse(value)
    rendered = " ".join(rendered.split())
    if len(rendered) > MAX_OUTLINE_VALUE_CHARS:
        return rendered[: MAX_OUTLINE_VALUE_CHARS - 3].rstrip() + "..."
    return rendered


def _indent_lines(lines: list[str], indent: str) -> list[str]:
    if not indent:
        return lines
    return [f"{indent}{line}" if line else "" for line in lines]


def _render_markdown_outline(record: FileRecord, limit: int) -> str:
    heading_pattern = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
    lines = _representation_header(record, "outline", "markdown_headings")
    headings = []
    for line_number, line in enumerate((record.content or "").splitlines(), start=1):
        match = heading_pattern.match(line)
        if match:
            headings.append(f"{match.group(1)} {match.group(2)}  <!-- line {line_number} -->")
    lines.extend(headings or ["# No markdown headings found."])
    return _render_byte_limited_text("\n".join(lines).rstrip() + "\n", limit)


def _render_json_structure(record: FileRecord, limit: int) -> str:
    lines = _representation_header(record, "outline", "json_structure")
    try:
        payload = json.loads(record.content or "")
    except json.JSONDecodeError as exc:
        lines.extend([f"# JSONDecodeError while generating structure: {exc}", "", _render_byte_limited_text(record.content or "", limit)])
        return "\n".join(lines).rstrip() + "\n"
    skeleton = _json_skeleton(payload)
    lines.append(json.dumps(skeleton, indent=2, ensure_ascii=False))
    return _render_byte_limited_text("\n".join(lines).rstrip() + "\n", limit)


def _json_skeleton(value: Any, depth: int = 0) -> Any:
    if depth >= MAX_JSON_STRUCTURE_DEPTH:
        return "<max depth omitted>"
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        items = list(value.items())
        for key, child in items[:MAX_JSON_OBJECT_KEYS]:
            output[str(key)] = _json_skeleton(child, depth + 1)
        if len(items) > MAX_JSON_OBJECT_KEYS:
            output["..."] = f"{len(items) - MAX_JSON_OBJECT_KEYS} more keys omitted"
        return output
    if isinstance(value, list):
        rendered_items = [_json_skeleton(item, depth + 1) for item in value[:MAX_JSON_SEQUENCE_ITEMS]]
        if len(value) > MAX_JSON_SEQUENCE_ITEMS:
            rendered_items.append(f"... {len(value) - MAX_JSON_SEQUENCE_ITEMS} more items omitted")
        return rendered_items
    return f"<{type(value).__name__}>"


def _render_yaml_key_outline(record: FileRecord, limit: int) -> str:
    lines = _representation_header(record, "outline", "yaml_keys")
    key_pattern = re.compile(r"^(?P<indent>\s*)(?:-\s*)?(?P<key>[^:#][^:]*):(?:\s*(?P<value>.*))?$")
    found = False
    for line_number, line in enumerate((record.content or "").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = key_pattern.match(line)
        if not match:
            continue
        found = True
        indent = match.group("indent")
        key = match.group("key").strip()
        value = (match.group("value") or "").strip()
        suffix = " ..." if value else ""
        lines.append(f"{indent}{key}:{suffix}  # line {line_number}")
    if not found:
        lines.append("# No YAML mapping keys found.")
    return _render_byte_limited_text("\n".join(lines).rstrip() + "\n", limit)


def _render_byte_limited_text(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    clipped = encoded[:limit].decode("utf-8", errors="ignore").rstrip()
    return f"{clipped}\n\n# ... content omitted after {limit} bytes ...\n"



def _line_count(text: str | None) -> int:
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _relative_id_for_path(path: Path, project_root: Path) -> str:
    return _relative_path(path, project_root)


def _is_stdlib_module(name: str) -> bool:
    top = name.split(".", 1)[0]
    stdlib = getattr(sys, "stdlib_module_names", set())
    return top in stdlib
