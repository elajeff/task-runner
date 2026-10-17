# Privacy

task runner is a local desktop application. It does not operate a task runner account service, collect usage analytics, or send telemetry to a task runner server.

## Local processing and storage

Document files, extracted text, generated results, task history, and provider settings are stored on the computer where task runner runs. Local text extraction and OCR process the selected files on the computer. The optional OCR model may be downloaded when OCR is first used; the document itself is not uploaded for local extraction or OCR.

## AI provider requests

When you explicitly request an AI-generated output or an AI agent task that reads a document, task runner sends the relevant prompt and extracted text to the AI provider and endpoint configured by you. That provider may process the information under its own terms and privacy policy. Review those terms before sending confidential or personal information. task runner does not choose a remote provider on your behalf beyond the provider you configured.

Local extraction and OCR can be used without making an AI request. If you configure a hosted provider, credentials are stored in the local `.env` file used by the application; do not share that file. The packaged Windows application keeps its settings under `%LOCALAPPDATA%\task-runner`.

## Contact and changes

For questions or to report a privacy issue, use the contact method listed in the project's GitHub repository. This policy may be revised as the software changes.

**Network statement:** This program will not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it. AI operations transfer the selected prompt and relevant document text to the provider configured by the user; the optional OCR model may be downloaded at first use.
