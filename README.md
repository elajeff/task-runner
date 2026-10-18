# task runner

**task runner** is a Windows desktop application for extracting text from documents, generating AI-assisted outputs, and completing custom tasks across files. It combines local document processing with optional AI tools and saves task progress for recovery after interruptions.

## Features

- **Document extraction:** Extract text from PDFs, Word documents, spreadsheets, CSV/TSV, plain text, Markdown, and images.
- **Local OCR:** Optionally recognize text in scanned PDFs and images. OCR runs locally; the model is downloaded when OCR is first used.
- **AI outputs:** Generate summaries, detailed notes, definitions, and questions using a configured provider.
- **Agent tasks:** Ask the agent to inspect, compare, or combine text files and save a result in a selected folder.
- **Results preview:** Read formatted results in a browser or open the saved files directly.
- **Recovery and file safeguards:** Task state is stored locally in SQLite. File operations are restricted to the selected workspace, and overwrites require approval. The agent does not run shell commands or arbitrary programs.

## Download for Windows

Download the latest **Windows x64 ZIP** from [GitHub Releases](../../releases/latest). Extract the complete `task-runner` folder and run `task-runner.exe`. Keep the other files in that folder; the executable depends on the bundled files. A separate Python installation is not required.

Releases are unsigned unless the release notes explicitly say otherwise. Code signing details and current status are documented in [CODE_SIGNING_POLICY.md](CODE_SIGNING_POLICY.md).

## Use the application

- **Document tools:** Select a file and choose **Extract text** for local extraction. Enable OCR for scanned pages or images. Select AI outputs only when you need generated content.
- **Results:** After processing, choose **View in browser**, **Open results folder**, or **Not now**. The results preview can be reopened later; the saved Markdown and text files are also available to copy or reuse.
- **Agent tasks:** Describe the outcome you need and select a working folder. If filenames are unknown, ask the agent to list the available files first.
- **Provider settings:** Configure the AI provider and credentials used for AI-generated outputs and agent tasks.

Local text extraction and OCR do not send document contents to an AI provider. When an AI output or agent task reads document content, relevant text is sent to the provider configured by the user.

## Run from source

Python 3.13 (64-bit on Windows) is recommended, particularly for optional OCR support. From the repository root, open PowerShell and run:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev,documents]"
.\.venv\Scripts\python.exe -m runtime.gui
```

To install optional OCR dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[ocr]"
```

The first OCR run may download the model and requires an internet connection. Normal selectable-text extraction does not require OCR.

## Tests

Run the suite from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Tests use local fixtures, temporary directories, and simulated provider responses. They cover task persistence and recovery, workspace restrictions, overwrite safeguards, provider error handling, document extraction, and GUI workflows. AI-related tests do not call a live provider or consume API quota; they do not verify a real API key, live model availability, network access, or OCR quality on a particular image.

## Build the Windows application

On a Windows x64 computer with 64-bit Python 3.13 installed, double-click `packaging\build-windows.bat`. The script creates a build environment, installs the required dependencies, runs tests, and packages the app. The icon builder prefers `assets/task-runner-icon.png`, supports `assets/task-runner-icon.jpg` for older checkouts, and creates `assets/task-runner.ico`. Keep the chosen source image and generated `.ico` in the repository so GitHub Actions uses the same icon without downloading another copy.

A successful build creates:

- `dist\task-runner\task-runner.exe` and its supporting files.
- `dist\task-runner-windows-x64.zip`, the bundle for distribution.

Test the packaged application before distribution. Do not commit `dist/` or other generated build output to the source branch. Tagged pushes (`v*`) trigger the GitHub Actions Windows build and release workflow. Check the workflow result before sharing a release.

## Data and configuration

- `.env.example` is the tracked configuration template; it must not contain real credentials.
- `.env` is private local configuration and is ignored by Git. The **Provider settings** page creates or updates it for a source installation.
- Source runs store local settings, task data, and the default workspace in the project directory. The packaged Windows app uses `%LOCALAPPDATA%\task-runner` for writable data and settings.
- `data/`, local workspace contents, environment folders, and build outputs are excluded from Git.

See [PRIVACY.md](PRIVACY.md) for data-handling details and [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt) for dependency and model notices.

## Limitations

Extraction attempts to preserve reading order, headings, paragraphs, and detected table structures; it does not reproduce the original page layout. Multi-column pages, merged or complex tables, charts, floating objects, handwriting, and poor scans may be reconstructed incorrectly. Verify important values against the source document. OCR quality depends on language/script support, image clarity, font, and layout.

Agent tasks work with text files in the selected workspace. They do not execute code or shell commands.

## License

The source code is licensed under the [Apache License 2.0](LICENSE). Third-party packages and optional OCR model weights may have separate licenses; see [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt).
