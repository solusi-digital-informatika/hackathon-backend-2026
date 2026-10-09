# Approved shot image generation

Default image configuration uses `AI_IMAGE_API_MODE=gemini`, `AI_IMAGE_MODEL=gemini-3.1-flash-image` and a separate `GEMINI_API_KEY` (or `GOOGLE_API_KEY`). It calls Google's native `generateContent` endpoint with text and image reference parts, requests IMAGE/TEXT output, and reads candidate `inlineData`. The gateway key is never reused for Google. Setup and unresolved account limitations are documented in [User Manual](../../USER_MANUAL.md) and shown in Shot Management.

Legacy `chat` and `images` modes remain available with `AI_API_KEY` and `AI_BASE_URL`. Chat mode sends multimodal Chat Completions without JSON response format; images mode sends an Images Generations request. All modes require actual image output. Text-only responses fail with `image_output_missing`; a model appearing in `/models` does not guarantee its underlying provider is configured for image output.

Images use the approved active shot revision's saved title, description and details. Approved non-archived project moodboards contribute reviewed visual direction; Gemini and chat modes also send up to three approved reference thumbnails. No moodboard is required. The stored job snapshot records the exact direction and references used.

Provider diagnosis: an empty response with `finish_reason=malformed_function_call` reports `image_provider_tool_error`. The client cannot execute an unavailable provider image tool. Provider model and finish reason are logged without prompts or API keys. This is distinct from malformed image data or a UI parsing error.

- `POST /projects/{project_id}/shot-images/generate`: `{shot_id, revision_id}`, returns 202 with the job.
- `POST /projects/{project_id}/shot-images/generate-approved`: queues all approved active shots, including browser-hidden shots. Unapproved shots are skipped.
- `GET /projects/{project_id}/shot-images`: persisted job states and per-version image URLs.
- `GET /projects/{project_id}/shot-images/config`: provider/model/configured flag and missing key name; never returns key values.
- `GET /projects/{project_id}/shot-images/{revision_id}/file`: the stored image, scoped to its project.

Jobs run in the background with two concurrent workers. Repeated requests reuse queued, running and successful jobs. Failed jobs may be retried. Approval and active revision are checked before queueing, before calling the provider and before publishing. A changed revision produces a stale job and no published image. Historical successful images stay associated with their original versions. Restart marks interrupted running jobs failed and resumes queued jobs; there is no automatic repeated paid request after a timeout.

PNG/JPEG/WebP output is validated before storage under `data/shot-images` (ignored by Git). The UI polls status every three seconds and displays previews/errors. This local implementation assumes a single backend process and has the same access model as existing project APIs.
