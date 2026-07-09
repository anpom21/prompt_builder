# Context Builder

Context Builder is a small desktop app for building structured, repository-aware JSON context structures.

It lets you add files or folders, discovers repo-local Python imports, previews what will be included, and copies the final JSON context structure to your clipboard so it can be pasted into an LLM.

The app is intended for coding workflows where you want to give an LLM the relevant project context without manually copying files one by one.

## Features

- Add files or folders through the UI.
- Drag and drop local files or folders into the app.
- Automatically include repo-local Python dependencies from imports.
- Ignore common virtual environment, cache, build, and dependency folders.
- Preview included file content before copying.
- Include files fully, truncate them, or exclude them.
- Choose an LLM task template such as code editing, debugging, review, architecture explanation, or refactor planning.
- Write the actual user prompt separately from the repository context.
- Copy the final JSON context structure directly to the clipboard.
- Export JSON context structures to disk.
- Save and load Context Builder sessions.

## Requirements

- Python 3.12+
- uv
- PySide6

## Install

On Ubuntu, run the installer from the repository root:

```bash
bash install_ubuntu.sh
```

The installer will:

- install `uv` if it is missing
- run `uv sync`
- install the desktop launcher
- install the SVG app icon
- install Material Icon Theme file icons used in the file tree

### Python dependencies

To install or refresh dependencies manually:

```bash
uv sync
```

### File icons

Context Builder can show Material Icon Theme file icons in the tree and flat file views.

The Ubuntu installer downloads the VS Code Material Icon Theme extension and copies its icon assets into the package automatically. To do it manually:

```bash
code --install-extension PKief.material-icon-theme

material_dir=$(find ~/.vscode/extensions -maxdepth 1 -type d -iname 'pkief.material-icon-theme-*' | sort | tail -n 1)
mkdir -p src/context_builder/icons/material-icon-theme
cp -a "$material_dir/icons" src/context_builder/icons/material-icon-theme/
```

The final folder should look like this:

```text
src/context_builder/icons/material-icon-theme/icons/python.svg
src/context_builder/icons/material-icon-theme/icons/yaml.svg
src/context_builder/icons/material-icon-theme/icons/markdown.svg
```

SVG is preferred for Ubuntu launchers because it scales cleanly across desktop icon sizes. Context Builder uses `logo.svg` when available and falls back to `logo.png`.

## Usage

Start the app:

```bash
uv run context-builder
```

Start the app with files or folders already loaded:

```bash
uv run context-builder path/to/file.py path/to/folder
```

Enable verbose logging:

```bash
uv run context-builder --verbose
```

You can combine startup paths with verbose logging:

```bash
uv run context-builder path/to/file.py --verbose
```

The legacy launcher file still works for local development:

```bash
uv run python main.py
```

## Basic workflow

1. Add files or folders with **Add File**, **Add Folder**, or drag and drop.
2. Review the discovered files in the tree or flat view.
3. Include, truncate, or exclude files as needed.
4. Select an LLM task template.
5. Write your user prompt.
6. Click **Copy Context**.
7. Paste the copied JSON into an LLM.

## How dependency discovery works

Context Builder parses Python imports and tries to resolve only repository-local dependencies.

It does not intentionally include external packages from virtual environments, `site-packages`, or common dependency folders. This keeps the context structure focused on project code rather than installed libraries.

The dependency graph in the JSON context structure is structural. It describes which local files import or depend on other local files. It is not an execution order.

## Settings

The settings panel lets you adjust:

- Project root override
- Import root overrides
- Maximum dependency depth
- Large file threshold
- Truncation size
- Hidden file inclusion
- Whether unchecked folder files should remain listed in the JSON

## Notes

- Files are read from disk, so save your work before importing or dragging files into the app.
- Large files can be excluded or truncated to keep context structures manageable.
- The JSON context structure includes the stable context-reading instructions, the selected LLM task, the user prompt, file records, and a dependency graph.
- Missing, external, or unresolved imports are skipped rather than invented.
