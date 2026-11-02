# task runner

A Windows desktop app that pulls the text out of documents, turns it into study material with an AI model of your choice, and runs small file tasks with an agent that is kept inside one folder.

Built with Python and Tkinter. Text extraction and OCR run on your own computer; only the AI features send text to a provider (Gemini, OpenAI, Anthropic, Ollama or any OpenAI-compatible server). Progress is saved as a job runs (agent tasks in SQLite, document jobs as checkpoint files), so an interrupted job can be resumed.

![The results page for a Word document, with its headings, bullet points and table kept](docs/images/results.png)

![The task runner window on the Document tools tab](docs/images/main-window.png)

The results page comes from extracting a made-up Word document, without an AI provider.

## What it does

- Extracts text from PDFs, Word documents, spreadsheets, CSV/TSV, text and Markdown files and images, keeping headings, lists and tables where it can.
- Optional local OCR for scanned PDFs and photos. The model downloads the first time you use it.
- Generates summaries, detailed notes, key definitions and practice questions with the AI provider you configure.
- Agent tasks: ask it to look through, compare or combine text files in a folder you pick and save the result there. It can't leave that folder, asks before overwriting anything, and can't run commands or programs.
- Shows the results as a formatted page in your browser, next to the saved Markdown and text files.

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

On a Windows x64 computer with 64-bit Python 3.13 installed, double-click `packaging\build-windows.bat`. The script creates a build environment, installs the dependencies, runs the tests and packages the app into:

- `dist\task-runner\task-runner.exe` and its supporting files.
- `dist\task-runner-windows-x64.zip`, the bundle for distribution.

Pushing a `v*` tag runs the same build in GitHub Actions and publishes a release.

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
