# Windows code signing

task runner can currently build an unsigned Windows folder bundle. Its GitHub Actions workflow also has an optional PFX-based Authenticode route for maintainers who already possess a trusted certificate. That PFX route is separate from SignPath Foundation and should not be used as a substitute for the SignPath integration.

## Current SignPath Foundation status

task runner has not yet been accepted by SignPath Foundation, and the current workflow does not submit artifacts to SignPath for signing. Do not claim that a release uses SignPath Foundation until the project is accepted and the integration is configured and verified.

After acceptance, use SignPath's current GitHub Actions integration and the trusted GitHub.com build system. The Windows build should run on GitHub-hosted Windows runners, upload the unsigned release ZIP as a workflow artifact, submit that artifact for SignPath signing, wait for approval/signing as required, and publish the signed result to the GitHub Release. Add only the SignPath-issued secrets and identifiers specified by its dashboard/documentation. Do not put signing credentials, API tokens, certificates, or passwords in the repository.

SignPath requires verifiable build provenance, and each release signing request requires manual approval. Its free OSS certificate is held by SignPath Foundation rather than provided as a PFX private key, so the existing PFX secrets do not activate it. Consult the current official instructions:

- <https://signpath.org/terms.html>
- <https://docs.signpath.io/trusted-build-systems/github>
- <https://docs.signpath.io/build-system-integration>

## Existing PFX-based signing option

This optional path is for a separate trusted certificate you already own and can export in PFX format. A self-signed certificate is not suitable for public distribution.

1. On a trusted computer, convert your PFX to Base64 (do not commit or upload the source PFX):

   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("publisher.pfx"))
   ```

2. Add these GitHub Actions repository secrets:
   - `WINDOWS_SIGNING_CERTIFICATE_PFX_BASE64`
   - `WINDOWS_SIGNING_CERTIFICATE_PASSWORD`

3. Run the Windows release workflow. The workflow signs `task-runner.exe` with SignTool, applies a SHA-256 timestamp, verifies the signature, and deletes the temporary PFX from the runner.

Never commit a PFX/P12 file, private key, API token or password. See [the project code-signing policy](../CODE_SIGNING_POLICY.md) and [privacy policy](../PRIVACY.md).
