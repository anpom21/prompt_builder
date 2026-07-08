from __future__ import annotations

from pathlib import Path

from prompt_builder.core import BuildRequest, BuildSettings, BundleBuilder


def write(path: Path, text: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def build(paths: list[Path], settings: BuildSettings | None = None, overrides: dict[str, str] | None = None):
    request = BuildRequest(
        input_paths=[str(path) for path in paths],
        settings=settings or BuildSettings(),
        file_overrides=overrides or {},
    )
    return BundleBuilder().build(request)


def test_project_root_and_relative_dependencies(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    (project / ".git").mkdir(parents=True)
    write(project / "pyproject.toml", "[project]\nname = 'demo'\n")
    write(project / "src" / "pkg" / "__init__.py", "")
    write(project / "src" / "pkg" / "a.py", "from .b import value\n")
    write(project / "src" / "pkg" / "b.py", "from .c import thing\n")
    write(project / "src" / "pkg" / "c.py", "thing = 1\n")

    result = build([project / "src" / "pkg" / "a.py"])
    bundle = result.bundle

    assert set(bundle) == {"schema_version", "user_prompt", "system_prompt", "files", "dependency_graph"}
    assert bundle["schema_version"] == 1

    file_ids = {item["id"] for item in bundle["files"]}
    assert {"src/pkg/a.py", "src/pkg/b.py", "src/pkg/c.py"}.issubset(file_ids)

    graph = {item["source_id"]: set(item["includes"]) for item in bundle["dependency_graph"]}
    assert graph["src/pkg/a.py"] == {"src/pkg/b.py"}
    assert graph["src/pkg/b.py"] == {"src/pkg/c.py"}


def test_ambiguous_from_import_prefers_submodule(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    write(project / "pyproject.toml", "[project]\nname = 'demo'\n")
    write(project / "pkg" / "__init__.py", "marker = True\n")
    write(project / "pkg" / "name.py", "value = 1\n")
    write(project / "pkg" / "mod.py", "from pkg import name\n")

    result = build([project / "pkg" / "mod.py"])
    bundle = result.bundle
    graph = {item["source_id"]: set(item["includes"]) for item in bundle["dependency_graph"]}

    assert graph["pkg/mod.py"] == {"pkg/name.py"}


def test_unchecked_dependency_remains_with_null_content(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    write(project / "pyproject.toml", "[project]\nname = 'demo'\n")
    write(project / "a.py", "import b\n")
    write(project / "b.py", "value = 1\n")

    result = build([project / "a.py"], overrides={"b.py": "excluded"})
    bundle = result.bundle

    dep = next(item for item in bundle["files"] if item["id"] == "b.py")
    assert dep["included"] is False
    assert dep["content"] is None
    graph = {item["source_id"]: set(item["includes"]) for item in bundle["dependency_graph"]}
    assert graph["a.py"] == {"b.py"}


def test_large_file_can_be_truncated(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    write(project / "pyproject.toml", "[project]\nname = 'demo'\n")
    write(project / "big.txt", "abcdefghijklmnopqrstuvwxyz" * 20)

    settings = BuildSettings(large_file_threshold=20, truncation_size=15)
    result = build([project / "big.txt"], settings=settings, overrides={"big.txt": "truncated"})
    bundle = result.bundle
    record = next(item for item in bundle["files"] if item["id"] == "big.txt")

    assert record["included"] is True
    assert record["content"] is not None
    assert len(record["content"]) <= 15
    assert record["truncation"]["limit_bytes"] == 15


def test_circular_imports_do_not_loop(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    write(project / "pyproject.toml", "[project]\nname = 'demo'\n")
    write(project / "a.py", "import b\n")
    write(project / "b.py", "import a\n")

    result = build([project / "a.py"])
    bundle = result.bundle

    file_ids = {item["id"] for item in bundle["files"]}
    assert file_ids == {"a.py", "b.py"}
    graph = {item["source_id"]: set(item["includes"]) for item in bundle["dependency_graph"]}
    assert graph["a.py"] == {"b.py"}
    assert graph["b.py"] == {"a.py"}
