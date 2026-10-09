# AI creative brief

`POST /projects/{project_id}/brief/generate`

Input: `source_name`, `content` (up to 50,000 characters), `shot_count`
(integer 1–30, default 7). Uses existing `AI_BASE_URL`, `AI_API_KEY`,
and `AI_TEXT_MODEL` when set, otherwise `AI_VISION_MODEL`. Keys remain server-side.

Returns HTTP 201 with `source_document` and `brief`. The brief includes
`version`, `creative_sections` (eight Markdown sections), `storyboard`, and
`generated_shot_ids`, alongside the existing direction fields. Unknown factual
details are marked `Belum ditentukan`; storyboard suggestions require human review.

All output is schema-validated before any records are saved. Unrelated input returns
422 `irrelevant_brief` with a reason. Incomplete creative input remains acceptable.
Provider errors return 502/503 without creating a source, brief, or shots.

The source, brief, creative plan are saved in one transaction. No shots or images are generated during brief creation.
Generating another brief creates a new version and retains existing shots. Repeated generation is a new version, not an idempotent retry.
The new `creative_brief_plans` table is created by the application's existing startup
schema initialization; no existing table columns need migration.

`GET /projects/{project_id}/brief` returns the active plan. `PUT` accepts all eight
`creative_sections` to persist human edits along with existing approval controls.
Editing sections does not automatically revise already-created shots; review them in
the Shot Board. Earlier records are retained, but a history browsing endpoint/UI is
not included in this change. Relevance classification is AI-based and can be wrong.

Validation: backend tests cover version preservation, exact shot counts, rejected
inputs without writes, section edits, and provider failures. Live provider checks use
a short incomplete creative brief and a standalone recipe.

## Explicit shot generation

`POST /projects/{project_id}/brief/storyboard` takes `brief_id` and `shot_count`
(integer 1?30, default 7). It uses the saved current brief to generate text details
only. Action, framing, camera movement, lighting, environment, subjects, transition
and an image prompt are preserved in the plan and in `shot_generation_details`.
The shot API returns those values as `generation_details`. No image endpoint is called.
Repeated requests for the same brief return its existing shots without duplication.
A changed brief returns 409. Existing shots are preserved. Future image generation
can combine saved details with reviewed moodboard references per shot; image
generation and background scheduling are not part of this change.
