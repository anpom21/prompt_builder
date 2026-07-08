# Prompt Builder

Prompt Builder is a small desktop app for building structured, repository-aware JSON prompt bundles.

It lets you add files or folders, discovers repo-local Python imports, previews what will be included, and copies the final JSON bundle to your clipboard so it can be pasted into an LLM.

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
- Copy the final JSON bundle directly to the clipboard.
- Export JSON bundles to disk.
- Save and load Prompt Builder sessions.

## Requirements

- Python 3.10+
- PySide6

## Install

Create and activate a virtual environment:

```bash
python -m venv .venv
```

On Windows:

```bash
.venv\Scripts\activate
```

On macOS/Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install PySide6
```

## Usage

Start the app:

```bash
python main.py
```

Start the app with files or folders already loaded:

```bash
python main.py path/to/file.py path/to/folder
```

Enable verbose logging:

```bash
python main.py --verbose
```

You can combine startup paths with verbose logging:

```bash
python main.py path/to/file.py --verbose
```

## Basic workflow

1. Add files or folders with **Add File**, **Add Folder**, or drag and drop.
2. Review the discovered files in the tree or flat view.
3. Include, truncate, or exclude files as needed.
4. Select an LLM task template.
5. Write your user prompt.
6. Click **Copy JSON**.
7. Paste the copied JSON into an LLM.

## How dependency discovery works

Prompt Builder parses Python imports and tries to resolve only repository-local dependencies.

It does not intentionally include external packages from virtual environments, `site-packages`, or common dependency folders. This keeps the prompt bundle focused on project code rather than installed libraries.

The dependency graph in the JSON bundle is structural. It describes which local files import or depend on other local files. It is not an execution order.

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
- Large files can be excluded or truncated to keep bundles manageable.
- The JSON bundle includes the stable bundle-reading instructions, the selected LLM task, the user prompt, file records, and a dependency graph.
- Missing, external, or unresolved imports are skipped rather than invented.