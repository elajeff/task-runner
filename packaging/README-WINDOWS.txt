task runner for Windows
======================

1. Extract the entire task-runner folder from this ZIP.
2. Double-click task-runner.exe. Keep the other files beside it; the app needs them.
3. Open Provider settings to configure an AI provider. Text extraction works locally;
   AI summaries and other generated outputs need a configured provider and available quota.
4. The optional OCR model downloads the first time you use OCR. It is not downloaded
   when task runner starts.

Your local settings, task history, and document results are stored under:
%LOCALAPPDATA%\task-runner

The API key is saved to the local .env file in that folder. Do not share that file.
Use the app's buttons to open its working folder and document results.

CODE SIGNING POLICY
task runner is preparing an application to SignPath Foundation; it has not yet been
approved or integrated. This build is unsigned unless Windows Properties reports a
valid digital signature. Do not assume a release is signed because of this notice.
If approved and integrated, the release page will state: “Free code signing provided
by SignPath.io, certificate by SignPath Foundation.” Check Properties > Digital
Signatures to verify the signer of a particular executable.

For source, setup, current release status, privacy policy, and code-signing policy,
see the project's GitHub repository README and CODE_SIGNING_POLICY.md.


If the build fails, the window remains open and the full output is saved in
`build-windows.log` in the project root. Include that log when reporting an issue.
The builder expects `pyproject.toml`, `runtime/`, and `packaging/` to be in this
project root; it does not require or depend on the name of the parent folder.
