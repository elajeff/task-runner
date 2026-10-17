# task runner

task runner is a desktop app for extracting text from documents, creating AI-assisted outputs, and carrying out custom tasks across files. It keeps task history locally and supports careful recovery after interruptions.

## What it does

- **Local document tools:** extract text from PDFs, Word documents, spreadsheets, CSV/TSV, plain text, Markdown, and images. Optional OCR handles scanned pages and images.
- **AI document outputs:** create summaries, detailed notes, definitions, or questions using an AI provider you configure.
- **Agent tasks:** compare or combine information across multiple text files and save a requested result in a chosen workspace.
- **Saved progress and recovery:** store task state in SQLite, record tool-action intent and results, and let you inspect uncertain actions after interruptions.
- **File safeguards:** constrain agent file operations to the selected workspace and require approval before replacing existing content. The agent does not execute shell commands or arbitrary programs.

task runner is written in Python. SQLite keeps task progress and recovery checkpoints, while a shared provider interface supports Gemini, OpenAI, Anthropic, Ollama, and compatible APIs. Document extraction uses `pdfplumber`, `python-docx`, and `openpyxl`; local OCR is optional through Indra OCR. The test suite uses local fixtures and simulated provider responses, so it can check common success and failure paths without consuming AI quota.

## Download for Windows

**Most users should download the latest Windows ZIP from [GitHub Releases](../../releases/latest).** Extract the complete `task-runner` folder and double-click `task-runner.exe`. The application is displayed as **task runner**; the dashed spelling is used for files and the repository. Keep the other files in the same folder; the executable depends on the bundled files. A separate Python installation is not required. The optional OCR model downloads when OCR is first used, not when the app starts.

If a Windows release is not published yet, the GitHub Actions workflow must complete successfully before a release asset is available. You can also build the Windows package yourself on a Windows x64 computer:

1. Install 64-bit Python 3.13.
2. Extract or clone this repository.
3. Double-click `packaging\build-windows.bat`. On the first run, it downloads the supplied app image from Imgur if `assets\task-runner-icon.jpg` is missing, then creates `assets\task-runner.ico`. The icon is used for the executable, window title bar, and taskbar.
4. When it succeeds, the ready-to-distribute bundle is `dist\task-runner-windows-x64.zip`.
5. Keep the generated `assets\task-runner-icon.jpg` and `assets\task-runner.ico` in the source repository so the release workflow uses the same icon. If the Imgur address returns a webpage instead of an image, save the actual image from your browser as `assets\task-runner-icon.jpg` and rerun the build.

You **can** upload that ZIP to a GitHub Release for users to download; they do not have to build the project themselves. Do not commit the generated `dist/` output or executable into the normal source branch. GitHub Releases are the appropriate place for binary downloads. For releases that use SignPath Foundation signing, use the approved SignPath integration with the trusted GitHub Actions build rather than uploading a locally built binary for signing, because SignPath verifies the binary's build origin.

To have GitHub Actions build and attach the ZIP automatically, push a version tag after reviewing the source and workflow:

```shell
git tag v0.1.0
git push origin v0.1.0
```

The workflow runs tests, builds the Windows bundle with PyInstaller, smoke-tests the GUI executable, and attaches the ZIP to the tagged release. The first Windows build must pass before distributing the release. A local build is useful for checking packaging; it is not evidence that the GitHub release workflow or code signing has passed. The repository should contain `assets/task-runner-icon.jpg` and `assets/task-runner.ico` after the first successful local build so releases do not depend on a live Imgur download.

### First publication to GitHub

1. Extract this project into a folder named `task-runner` and open PowerShell in that folder (File Explorer address bar → type `powershell` → Enter).
2. Double-click `packaging\build-windows.bat` once so the icon is downloaded/generated and the Windows bundle can be tested. If successful, keep `assets\task-runner-icon.jpg` and `assets\task-runner.ico` for the repository.
3. Create an **empty** public repository named `task-runner` on GitHub. Do not have GitHub add a README or license, because they already exist here.
4. In PowerShell, run the following commands, replacing the URL with your repository's HTTPS URL:

   ```powershell
   git init -b main
   git add .
   git status --short
   ```

   Check the staged list. It must not include `.env`, local databases, `workspace` results, `.venv*`, `build/`, or `dist/`. The icon files under `assets/` are intentional source assets and should be committed.

   ```powershell
   git commit -m "Initial task runner release"
   git remote add origin https://github.com/YOUR_USERNAME/task-runner.git
   git push -u origin main
   ```

5. Create and push a version tag to trigger the Windows release workflow:

   ```powershell
   git tag v0.1.0
   git push origin v0.1.0
   ```

6. Open the repository's **Actions** tab and wait for the Windows workflow to pass. Then check **Releases** for `task-runner-windows-x64.zip`. The release workflow builds the executable; do not commit `dist/` or upload the standalone `.exe` to the source branch.

If the repository already exists or contains commits, clone it first and copy these project files into that clone instead of running `git init` again.

## Run from source

Python 3.13 (64-bit on Windows) is recommended, particularly for optional OCR support. From the repository root, open PowerShell and run:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev,documents]"
```

Launch the desktop app:

```powershell
.\.venv\Scripts\python.exe -m runtime.gui
```

Optional local OCR dependencies can be added separately:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[ocr]"
```

### Run the test suite

From the project root, after the install steps above, run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The tests use temporary directories, small document fixtures, and fake provider responses. For AI-related tests, task runner is given fixed example responses instead of contacting Gemini, OpenAI, or another service. This checks how the app handles results and errors without needing an API key or using quota; it does **not** prove a real API key, current model, network connection, or OCR model works. Tests also check recovery, workspace restrictions, overwrite safeguards, and extraction of common document structures.

### Build the Windows application

On Windows, install 64-bit Python 3.13 and make sure `py -3.13` works in a terminal. Then double-click `packaging\build-windows.bat` from File Explorer. The script creates an isolated `.venv-build`, installs the build and OCR dependencies, runs the tests, builds the GUI, and packages the output. An internet connection is required on the first run to install packages and later if the optional OCR model needs to be downloaded.

On success, the script reports these files:

- `dist\task-runner\task-runner.exe` — the executable (keep the rest of the `task-runner` folder beside it).
- `dist\task-runner-windows-x64.zip` — the bundle to upload to a GitHub Release.

The build window stays open at the end. If a step fails, read the error printed there or open `build-windows.log` in the repository root; send that log when troubleshooting. The build script deliberately does not sign the local executable. Public signed releases should use the approved signing workflow after code signing is set up.

GitHub Actions uses the same project build spec from `.github/workflows/windows-release.yml` when you push a version tag. For release distribution, prefer the workflow-generated ZIP so the packaged build can be tested and, once configured, signed in CI.

## How to use it

- **Document tools:** choose a file and select **Extract text** for local processing. Enable OCR for images or scanned pages. Select AI outputs only when you want AI-generated content. Use **View latest results** to open a formatted preview in your browser, **Open latest results** to open that run's folder, or **Browse all results** to find older runs. Results are saved as regular Markdown/text files too, so you can reuse them elsewhere.
- **Agent tasks:** describe a task involving one or more text files. The agent can list files in the working folder if you do not know their names. You can choose an existing project folder; you do not need to move task runner or copy files into a fixed folder.
- **Provider settings:** configure the AI service and credentials you want to use. Local text extraction and OCR do not send document contents to an AI provider. When you request AI-generated output or an agent task that reads a document, relevant text is sent to the provider you configured.

### Extraction limitations

task runner attempts to preserve useful reading order, paragraphs, headings, and detected table structure; it does not reproduce the original page design. Complex tables, merged cells, multi-column pages, charts, floating objects, handwriting, and poor scans may be reconstructed incorrectly. Check important values against the original file. OCR quality depends on the script, font, clarity, and layout. See the [Indra OCR project](https://github.com/datalab-to/indra) and [model card](https://huggingface.co/datalab-to/indra-ocr) for current language support and model licensing.

Document outputs also include a `results.html` page. After a run, choose **View in browser**, **Open results folder**, or **Not now**. The **View latest results** button reopens the formatted preview later, while **Open latest results** and **Browse all results** provide access to the files. The original `.md` and `.txt` files remain available for copying or reuse. New runs no longer create a separate `START_HERE.txt` index.

## Data and project structure

```text
runtime/          Application runtime: GUI, CLI, configuration, providers, tools, agent engine, and storage
tests/            Offline behavior and regression tests
packaging/        Windows build script, PyInstaller spec, and release notes
.github/workflows Windows build, test, and release automation
workspace/        Default agent workspace (local content is ignored by Git)
data/             Local SQLite database and backups (ignored by Git)
```

For a source checkout, settings and task data default to the project directory. The frozen Windows app stores its settings and data under `%LOCALAPPDATA%\task-runner`. If that folder does not exist, it migrates data from the older `%LOCALAPPDATA%\TaskRunner` location when present. The Python import package remains named `runtime` (`runtime.gui` and `runtime.cli`); that is an internal module name, not the product name. Older document-job state filenames are also recognized so unfinished work from older versions can be resumed.

### `.env` and `.env.example`

These files have different purposes:

- `.env.example` is a safe template tracked in Git. It documents supported settings with example defaults and blank credential fields; it must never contain your real API key.
- `.env` is your private local settings file. The app's **Provider settings** page creates or updates it when you save a provider configuration. In a source checkout it is in the project root; in the packaged Windows app it is under `%LOCALAPPDATA%\task-runner`.

You do not normally need to create `.env` manually when using the GUI. If you want to configure the source environment by hand, copy `.env.example` to `.env` and enter your own values. `.env` is excluded by `.gitignore` because it may contain secrets. **Keep your local `.env`; do not commit it.** The `.env.example` file is the safe template intended for GitHub.

Important: `.gitignore` does not stop tracking a file that was already committed. Before your first commit, check that `.env` is not tracked:

```powershell
git check-ignore -v .env
git ls-files -- .env
```

The first command should show the ignore rule; the second should print nothing. If the second command lists `.env`, remove it from Git's index while keeping your local file:

```powershell
git rm --cached .env
```

Then review `git status` before committing. If a real API key was ever committed or pushed, revoke/rotate it; deleting the file in a later commit does not remove the secret from Git history. See [Privacy](PRIVACY.md) for details about local storage and when a configured AI provider receives document text.

## Code signing policy

**Current status:** task runner has not yet been approved by SignPath Foundation, and this package does not claim to be signed by them. Until an approved integration is enabled, releases are unsigned unless a release explicitly states otherwise. The maintainer intends to apply for SignPath Foundation code signing; the policy and signing state will be updated if accepted and integrated.

If approved and integrated, the signed release page will state: **“Free code signing provided by SignPath.io, certificate by SignPath Foundation.”** Each signed artifact will be built from the reviewed repository source via GitHub Actions and submitted through the SignPath signing workflow. See [Code signing policy details](CODE_SIGNING_POLICY.md) and [Windows signing notes](packaging/CODE_SIGNING.md).

## Tests and scope

See [Run from source](#run-from-source) for the exact test command and coverage explanation. task runner is a focused desktop/portfolio project, not a general-purpose workflow orchestration platform. The agent reads and writes text files inside the selected workspace; it does not run code or shell commands.

## License

task runner source is licensed under the Apache License 2.0; see [`LICENSE`](LICENSE). Third-party Python packages and optional OCR model weights are subject to their own licenses, listed in [`THIRD_PARTY_NOTICES.txt`](THIRD_PARTY_NOTICES.txt).
