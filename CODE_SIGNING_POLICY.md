# Code signing policy

## Current status

task runner is preparing an application to the SignPath Foundation. It has not yet been accepted, and current releases must not be represented as signed by SignPath Foundation unless their executable has a verifiable SignPath Foundation signature. Until a trusted signing integration is active, the app may be distributed unsigned or with another explicitly identified trusted certificate.

If the project is accepted and the integration is activated, the release and download pages will state: **“Free code signing provided by SignPath.io, certificate by SignPath Foundation.”** Each signed binary will be built from reviewed source in the public repository through GitHub Actions and submitted through the trusted SignPath integration. The signed artifact will be attached to the corresponding GitHub Release only after signing is verified.

## Responsibilities

task runner is maintained as an individual open-source project. The repository maintainer is responsible for reviewing source changes, checking the Windows build and release workflow, and approving release signing requests. External contributions must be reviewed before merge. If additional maintainers are added, the repository will document which members may commit/review changes and which member(s) approve signing requests. SignPath Foundation's required access controls and multi-factor authentication will be enabled for all relevant accounts before signing is activated.

Before submitting this repository publicly, replace this paragraph with named people or links to the real repository's contributor/maintainer groups if the application requires those references.

## Privacy

task runner stores files, results, and task history locally. Local extraction and OCR do not send document content to an AI provider. When the user requests AI output, the relevant prompt and extracted text are sent to the provider configured by that user. task runner does not send telemetry to a task runner-operated server. The full statement is in [Privacy](PRIVACY.md).

## Release verification

Users should download Windows packages from the project's GitHub Releases page. For a signed build, right-click `task-runner.exe`, open Properties, and inspect the Digital Signatures tab. If the executable has no valid signature, it must not be described as signed. A signed release is intended to provide a verifiable link between repository source and the downloadable build, not a guarantee that the software is free of bugs.
