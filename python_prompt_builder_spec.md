# Spec: Python Prompt Context Builder

Label: `ready-for-agent`

## Problem Statement

Developers often need to ask an LLM to modify, review, debug, or explain code, but copying the right context manually is slow, error-prone, and inconsistent. A single file is often insufficient because the LLM also needs repo-local dependencies, configuration files, and related context. Manually collecting those files leads to missing imports, duplicate content, noisy absolute paths, accidental inclusion of virtual environments or generated artifacts, and prompts that are hard to validate or reuse.

The user wants a Python desktop app that builds structured, context-aware prompts. The app should accept files and folders, discover repo-local Python dependencies, allow the user to curate which files are included, and copy a clean JSON payload to the clipboard for pasting into an LLM.

## Solution

Build a PySide Qt desktop application for constructing LLM prompt bundles.

The app allows the user to enter a user prompt, drag and drop files or folders from VS Code or the OS file manager, inspect discovered files and dependencies in a tree UI, include or exclude files with checkboxes, preview file contents, and copy a normalized pure JSON context bundle to the clipboard.

The application discovers Python dependencies using AST-based import parsing and repo-local resolution. It detects the project root, detects import roots such as the repo root and `src`, supports absolute and relative Python imports, recursively discovers dependencies up to a configurable depth, excludes external packages and virtual environments, deduplicates files by canonical absolute path, and preserves dependency edges in a dependency graph.

The clipboard output is pure JSON with a normalized `files` array and `dependency_graph`, rather than separate duplicated `scripts` and `dependencies` arrays.

## Domain Glossary

* **Prompt Bundle**: The complete JSON object copied to the clipboard.
* **User Prompt**: The task-specific instruction entered by the user.
* **System Prompt**: A template-based or custom instruction describing how the LLM should behave.
* **Project Root**: The detected root of the repository or Python project.
* **Import Root**: A directory from which Python import names are resolved, such as the project root or `src`.
* **Direct File**: A file explicitly dropped or selected by the user.
* **Folder File**: A file discovered by recursively scanning a dropped folder.
* **Dependency File**: A repo-local Python file discovered through imports.
* **Context Tree**: The UI tree showing direct files, folder files, dependencies, reused dependencies, skipped files, and excluded files.
* **Dependency Graph**: A normalized list of import relationships between files.
* **Reused Node**: A dependency that appears under multiple parents in the tree but is stored once in the output.
* **Skipped Dependency**: An import that was detected but not included because it could not be resolved, exceeded depth, was external, was ignored, or violated size/type constraints.
* **Excluded File**: A file found by the app but not included in the prompt content.

## User Stories

1. As a developer, I want to enter a task-specific user prompt, so that the copied context tells the LLM what I need done.
2. As a developer, I want the clipboard output to be pure JSON, so that it is structured, validatable, reusable, and easy to paste into an LLM.
3. As a developer, I want the output to include both my user prompt and system prompt, so that the LLM receives behavior instructions and task instructions together.
4. As a developer, I want the system prompt to use templates, so that I can quickly choose common modes like code editing, review, debugging, or architecture explanation.
5. As a developer, I want to customize the system prompt when needed, so that I can adapt the LLM behavior for unusual tasks.
6. As a developer, I want to drag a Python file from VS Code into the app, so that I can quickly build context from the file I am working on.
7. As a developer, I want to drag a folder from VS Code into the app, so that I can include a larger feature area or package.
8. As a developer, I want to add files through a file picker, so that I can use the app even when drag-and-drop is inconvenient.
9. As a developer, I want to add folders through a folder picker, so that I can import context without using drag-and-drop.
10. As a developer, I want dropped files to be read from disk, so that the app behavior is simple and predictable.
11. As a developer, I want the app to ignore unsaved VS Code buffers, so that version one does not require editor integration.
12. As a developer, I want the app to show a note that files are read from disk, so that I remember to save files before importing.
13. As a developer, I want the app to detect the project root automatically, so that repo-relative paths and dependency resolution work without setup.
14. As a developer, I want the app to detect `.git` as the preferred project root marker, so that repository boundaries are respected.
15. As a developer, I want the app to detect Python project markers when `.git` is absent, so that non-Git Python projects still work.
16. As a developer, I want to manually override the detected project root, so that I can correct ambiguous or unusual project structures.
17. As a developer, I want the app to show the detected project root, so that I can verify the context boundary.
18. As a developer, I want each file to store both absolute and repo-relative paths, so that the app can reload files while the LLM sees clean project-relative paths.
19. As a developer, I want the copied JSON to emphasize repo-relative paths, so that the LLM sees a portable project structure.
20. As a developer, I want absolute paths retained in metadata, so that sessions can be reloaded and files can be reopened locally.
21. As a developer, I want Python imports to be parsed with AST, so that import discovery is reliable and not based on fragile text matching.
22. As a developer, I want only repo-local dependencies to be included, so that standard library and installed package code do not flood the prompt.
23. As a developer, I want imports from virtual environments to be ignored, so that the app does not include `.venv`, `venv`, or external package files.
24. As a developer, I want import statements preserved in the dependency graph, so that the LLM can understand why a file was included.
25. As a developer, I want recursive dependency discovery, so that dependencies of dependencies are included when relevant.
26. As a developer, I want dependency recursion to have a default maximum depth of 5, so that context discovery is useful without exploding across the whole repo.
27. As a developer, I want to configure dependency depth, so that I can choose direct-only, shallow, deep, or unlimited discovery depending on the task.
28. As a developer, I want skipped dependencies to be listed with reasons, so that I can understand missing context.
29. As a developer, I want circular imports to be handled safely, so that dependency discovery does not loop forever.
30. As a developer, I want repeated dependencies deduplicated by canonical absolute path, so that the JSON does not contain duplicate file contents.
31. As a developer, I want every dependency edge preserved even when a file is deduplicated, so that the import structure remains accurate.
32. As a developer, I want reused dependencies to appear under each importing parent in the UI, so that the tree reflects the actual dependency hierarchy.
33. As a developer, I want reused dependency checkboxes to stay synchronized, so that checking or unchecking one occurrence affects the underlying file consistently.
34. As a developer, I want reused dependencies to have a visual indicator, so that I understand why the same file appears in multiple places.
35. As a developer, I want the copied JSON to use one normalized `files` array, so that every file appears at most once.
36. As a developer, I want the copied JSON to include a `dependency_graph`, so that relationships are represented without duplicating content.
37. As a developer, I want direct files, folder files, and dependency files to be identified by `context_type`, so that the LLM can distinguish why each file was included.
38. As a developer, I want folder-imported files to use `file_from_folder`, so that they are distinguishable from directly dropped files.
39. As a developer, I want dependencies discovered from folder-imported files to use `file_from_folder_dependency`, so that their origin is clear.
40. As a developer, I want folder drops to recursively scan useful text/source/config/doc files, so that folder import captures relevant context.
41. As a developer, I want virtualenvs, caches, build outputs, generated outputs, checkpoints, and common artifact directories ignored by default, so that folder import does not produce noisy or huge prompts.
42. As a developer, I want approved file extensions to include Python, typing stubs, TOML, YAML, JSON, Markdown, text, INI, CFG, and example environment files, so that normal project context is included.
43. As a developer, I want binary files skipped by default, so that the prompt remains text-focused.
44. As a developer, I want large files flagged before inclusion, so that one file does not consume the entire prompt budget.
45. As a developer, I want large files excluded by default, so that importing folders is safe.
46. As a developer, I want to include a large file manually, so that I can override the default when the file is important.
47. As a developer, I want to include a truncated version of a large file, so that I can provide partial context without blowing the budget.
48. As a developer, I want truncation metadata in the JSON, so that the LLM knows the file is incomplete.
49. As a developer, I want total context size shown in the UI, so that I can manage prompt size before copying.
50. As a developer, I want per-file size shown in the UI, so that I can identify expensive files.
51. As a developer, I want unchecked dependency files to remain in the JSON with `content: null`, so that the LLM knows a dependency exists but was excluded.
52. As a developer, I want unchecked unrelated folder files moved out of the main `files` list or omitted by setting, so that the output stays clean.
53. As a developer, I want dependency graph edges preserved for unchecked files, so that missing-context warnings are explicit.
54. As a developer, I want warnings when an included file depends on an unchecked file, so that I can decide whether to re-include it.
55. As a developer, I want a three-panel UI layout, so that prompt entry, context curation, and file preview are visible together.
56. As a developer, I want the user prompt input at the top, so that the primary task is always visible.
57. As a developer, I want the context tree on the left, so that I can curate files and dependencies.
58. As a developer, I want file preview and details on the right, so that I can inspect selected files before copying.
59. As a developer, I want action buttons and status at the bottom, so that copy/export/session actions are easy to find.
60. As a developer, I want a tree view by default, so that dependency hierarchy is clear.
61. As a developer, I want an optional flat list view, so that I can sort, search, filter, and bulk-select files.
62. As a developer, I want checkboxes beside each file, so that I can control exactly what content is included.
63. As a developer, I want direct files visually distinct from dependencies, so that I can understand what I explicitly imported.
64. As a developer, I want dependencies greyed out relative to direct files, so that discovered context is visually subordinate.
65. As a developer, I want folders to have folder icons and files to have file icons, so that the tree is easy to scan.
66. As a developer, I want skipped and excluded files grouped separately, so that I can inspect what was left out.
67. As a developer, I want search/filter in the file list, so that I can quickly find a file in large imports.
68. As a developer, I want bulk include and exclude actions, so that I can curate many files efficiently.
69. As a developer, I want a copy JSON button, so that the completed prompt bundle goes directly to the clipboard.
70. As a developer, I want the app to validate the JSON before copying, so that I do not paste malformed context.
71. As a developer, I want a confirmation/status message after copying, so that I know the clipboard was updated.
72. As a developer, I want to save and load sessions, so that I can reuse a prompt bundle setup later.
73. As a developer, I want to export the JSON to a file, so that I can archive or share prompt bundles.
74. As a developer, I want diagnostics included in the output, so that unresolved imports, skipped files, and warnings are visible to the LLM and to me.
75. As a developer, I want import roots detected automatically, so that `src`-layout projects resolve correctly.
76. As a developer, I want manual import-root overrides, so that unusual repos can still be handled.
77. As a developer, I want relative imports resolved correctly, so that package-local dependencies are included.
78. As a developer, I want ambiguous `from package import name` imports handled practically, so that submodules are preferred when present.
79. As a developer, I want package `__init__` files included when needed, so that package exports are not missed.
80. As a developer, I want missing imports reported instead of failing the whole import, so that one unresolved dependency does not block the workflow.
81. As a developer, I want syntax errors in imported files reported clearly, so that I understand why dependency discovery may be incomplete.
82. As a developer, I want unreadable files reported clearly, so that permission issues do not fail silently.
83. As a developer, I want the UI to remain responsive during folder scans, so that large imports do not freeze the app.
84. As a developer, I want scan progress shown, so that I know the app is working during recursive discovery.
85. As a developer, I want cancellation during long scans, so that I can stop an accidental large import.
86. As a developer, I want deterministic output ordering, so that copied JSON can be compared across runs.
87. As a developer, I want files identified by stable repo-relative IDs, so that dependency graph edges are readable.
88. As a developer, I want content hashes in metadata, so that I can detect whether files changed between sessions.
89. As a developer, I want the application architecture to allow future VS Code extension integration, so that native editor commands can be added later without rewriting import logic.
90. As a developer, I want versioned schema metadata, so that future output changes can be handled safely.

## Implementation Decisions

1. The application will be a Python desktop app built with PySide Qt.

2. The clipboard output will be pure JSON only. No Markdown wrapper will be used.

3. The top-level prompt bundle will include schema version, user prompt, resolved system prompt, project metadata, settings, files, dependency graph, skipped dependencies, excluded files, and diagnostics.

4. The JSON output will use a normalized `files` array plus a `dependency_graph`. It will not use separate duplicated `scripts` and `dependencies` arrays.

5. Each file record will include a stable ID, filename, context type, absolute path, repo-relative path, inclusion state, source metadata, size metadata, optional truncation metadata, and content when included.

6. The app will store both absolute paths and repo-relative paths. Absolute paths are for app operations and session reloads; repo-relative paths are for LLM-facing structure.

7. The app will detect the project root using a hybrid strategy:

   * nearest parent containing `.git`
   * nearest parent containing Python project markers
   * nearest parent containing common dependency/config markers
   * fallback to the dropped file or folder parent
   * manual UI override

8. The detected project root will be visible in the UI and editable through a manual override control.

9. Import roots will be auto-detected. The default import roots will include the project root and common source roots such as `src`.

10. Manual import-root overrides will be supported for unusual project layouts.

11. Python dependency discovery will use AST parsing. It will inspect import nodes rather than using text matching.

12. Dependency discovery will use explicit repo-local file resolution only. It will not introspect runtime imports or import external modules.

13. External packages, standard library modules, `site-packages`, virtual environments, and ignored directories will not be included as dependencies.

14. Dependency discovery will be recursive by default.

15. The default maximum dependency depth will be 5.

16. Dependency depth will be configurable through the UI.

17. Circular imports will be handled by tracking canonical file identity and visited graph edges.

18. Files will be deduplicated by canonical absolute path.

19. Dependency relationships will not be deduplicated away. Every import edge will be preserved in the dependency graph.

20. Reused dependencies will appear under each importing parent in the tree UI, but all occurrences will share the same underlying inclusion state.

21. Reused dependencies will have a subtle reused/already-included visual indicator.

22. The app will support absolute imports in repo-root and `src`-layout projects.

23. The app will support relative Python imports using package-aware resolution.

24. For ambiguous `from package import name` imports, the resolver will prefer a matching submodule file or package before falling back to the package initializer.

25. Package initializer files will be included when needed, with a setting allowing stricter or more aggressive initializer inclusion later.

26. Folder drops will recursively scan files, but only approved text/source/config/doc file types will be included by default.

27. Folder scans will ignore common virtualenv, cache, build, artifact, output, dependency, and checkpoint directories by default.

28. Binary files will be skipped by default.

29. Large files will be flagged in the UI, excluded by default, and optionally included fully or as truncated content.

30. Truncated files will include explicit truncation metadata in the JSON.

31. Unchecked files that are part of dependency relationships will remain in the main `files` array with `included: false` and `content: null`.

32. Unchecked unrelated folder files will be moved to `excluded_files` or omitted according to an output setting.

33. Dependency graph edges will remain present even if the target file is unchecked.

34. The app will show warnings when included files depend on unchecked files.

35. Version one will read files from disk only.

36. Version one will ignore unsaved VS Code editor buffers.

37. The backend import API will be designed so that a future VS Code extension can call the same import logic.

38. Version one will support standard PySide drag-and-drop from VS Code Explorer and the OS file manager.

39. Version one will also support Add File and Add Folder buttons.

40. The main window will use a three-panel layout:

* prompt input on top
* context tree on the left
* file preview/details on the right
* status/actions at the bottom

41. The tree view will be the default context curation UI.

42. A flat list view will also be available for searching, filtering, sorting, and bulk selection.

43. File and folder icons will be shown in the tree.

44. Dependencies will be visually subordinate to direct imports, including greyed styling.

45. Checkboxes will control inclusion of file content.

46. Checkbox state for reused dependency nodes will be synchronized.

47. The system prompt will be template-based by default.

48. The system prompt will have an advanced editable mode for custom behavior.

49. Built-in system prompt templates will include at least:

* code editing with diff-oriented output
* code review
* debugging assistant
* architecture explanation
* refactor planning
* custom

50. The copied JSON will contain the resolved full system prompt, not only the template identifier.

51. The app will validate the prompt bundle before copying it to the clipboard.

52. The app will show copy status, included/excluded counts, warnings, and approximate context size.

53. Sessions will be saveable and loadable so prompt bundles can be reused.

54. JSON export to a file will be supported.

55. The app will include diagnostics for unresolved imports, skipped dependencies, large files, syntax errors, unreadable files, and ignored files.

56. Output ordering will be deterministic.

57. The schema will be versioned from the first implementation.

58. The implementation should separate backend context-building logic from PySide UI code, so the same backend can be tested directly and reused by future integrations.

59. The highest-value internal seam should be an application-level context-building service that accepts paths, prompt fields, settings, and project-root/import-root options, then returns a complete prompt bundle plus diagnostics.

60. The UI should call the context-building service rather than duplicating scanning, parsing, or schema-building logic.

## Testing Decisions

1. The primary testing seam will be the application-level context-building workflow: given input paths, project settings, prompt text, and inclusion settings, assert the resulting prompt bundle and diagnostics.

2. This seam is intentionally higher-level than individual parser functions. It tests the behavior the user cares about: what files are included, what dependencies are discovered, what is skipped, and what JSON is produced.

3. Unit tests may still exist for low-level import resolution, but the core acceptance tests should avoid overfitting to implementation details.

4. Good tests should verify external behavior:

   * output schema validity
   * included and excluded files
   * dependency graph edges
   * skipped dependency reasons
   * path normalization
   * deduplication behavior
   * checkbox inclusion effects
   * large-file behavior
   * folder-scan filtering
   * diagnostics

5. Good tests should not assert private implementation details such as internal AST traversal order, widget internals, private helper names, or exact intermediate data structures unless those structures are public contracts.

6. The main backend module to test is the prompt-bundle builder.

7. The import resolver should be tested through realistic miniature project fixtures.

8. The folder scanner should be tested through temporary directory fixtures containing included file types, ignored directories, binary files, large files, and nested source files.

9. The dependency graph builder should be tested through fixture projects with direct imports, nested imports, relative imports, `src` layout, duplicate dependencies, and circular imports.

10. The schema serializer should be tested by validating produced JSON against the expected schema contract.

11. The inclusion/exclusion behavior should be tested by toggling files and asserting content presence, `content: null`, excluded-files behavior, and graph preservation.

12. The large-file policy should be tested by creating files over the configured size limit and asserting default exclusion, manual full inclusion, and truncation metadata.

13. The UI should have lighter tests focused on user-visible behavior:

* files can be dropped or selected
* tree rows appear
* checkboxes update inclusion state
* selecting a file updates the preview panel
* copy button calls the bundle builder and clipboard service
* warnings/status are displayed

14. UI tests should not deeply inspect PySide internals where backend tests already cover the behavior.

15. Clipboard behavior should be tested through an abstraction around clipboard writing, so tests can assert copied text without depending on the OS clipboard.

16. Session save/load should be tested by saving a bundle/session, loading it, and asserting the restored user-visible state.

17. Prior art could not be inspected because no repository was provided. When implementing in an existing codebase, prefer existing test fixtures, temporary-directory test helpers, schema validation patterns, and UI test conventions already present in that repo.

## Out of Scope

1. Building a VS Code extension in version one.
2. Reading unsaved VS Code editor buffers.
3. Runtime Python import introspection.
4. Importing external installed package source code.
5. Supporting non-Python dependency discovery in version one.
6. Semantic code summarization.
7. Automatic token counting for every LLM provider in version one.
8. Automatic prompt optimization or compression beyond large-file truncation.
9. Editing files from inside the app.
10. Applying LLM-generated diffs.
11. Sending prompts directly to an LLM API.
12. Managing API keys.
13. Git operations.
14. Repository indexing beyond the current project scan.
15. Binary file understanding.
16. Notebook cell-aware parsing.
17. Secret scanning beyond basic ignored-file and `.env`-style exclusion defaults unless added as a later feature.
18. Publishing to an issue tracker until a target repository/project is provided.

## Further Notes

No repository was available in this conversation, so codebase exploration, ADR review, prior-art test discovery, and issue tracker publication could not be performed. This spec is ready to paste into an issue tracker and label with `ready-for-agent`.

Recommended first implementation milestone:

1. Build the backend context-bundle service.
2. Support file/folder import from paths.
3. Implement project-root and import-root detection.
4. Implement AST-based dependency discovery.
5. Implement normalized JSON schema output.
6. Add temporary-directory tests around realistic miniature Python projects.
7. Build the PySide shell UI around the tested backend.
8. Add clipboard copy and status reporting.
9. Add save/load sessions and JSON export.
10. Polish tree/flat views, icons, warnings, and large-file UX.

Recommended test seam selected on behalf of the user:

The main seam should be the context-bundle builder: given paths, prompt settings, dependency settings, inclusion overrides, and project/import-root settings, it returns a complete prompt bundle and diagnostics. This gives the most coverage with the fewest fragile tests and keeps the UI thin.
