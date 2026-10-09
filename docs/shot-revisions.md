# Shot revision flow

The shot keeps its stable ID. The revision graph uses `shot_revisions` and
`shot_revision_heads`; existing direction-specific versions remain separate.
These tables are created by the existing startup schema initializer.

- `GET /projects/{project_id}/shots/{shot_id}/revisions` initializes a durable v1
  snapshot for existing shots and returns all branches plus the current head.
- `POST` to the same route takes `parent_id`, `change_note`, and `mode` (`manual`
  or `ai`). Manual branches can supply title, description and detail fields.
  AI regeneration generates text details only. Each new revision gets max(version)+1.
- `POST .../revisions/{revision_id}/review` takes decision (`approve`/`reject`),
  `expected_active_id`, and a review note. Pending revisions do not change the shot.
  Approval merges only when the branch parent is still current. Rejected branches
  and original snapshots remain stored. Review timestamps and notes are recorded.

The original v1 is marked baseline unless previously approved; it is not represented
as a human-approved proposal. Approval is a human action in the current single-user
prototype; it does not establish authenticated reviewer identity.

Shot row locks serialize increments and merges. An outdated branch cannot overwrite
a newer head. Create a new revision from the current version with the desired changes.
Direct title/description/status updates and deletion are blocked after revision history
is initialized; sequence reordering is still allowed. No image generation is triggered.

Open **Revisions** on a Shot Board card to select a version, compare base/proposal,
create a manual or AI branch, and approve or reject it. The shared selectable graph
component lives in frontend `core/ui/RevisionGraph`.
# Image approval gate

History exposes `can_generate_image` per version. Only the active approved version of an approved shot is eligible. Pending, rejected, unapproved baseline and superseded versions are blocked. The original baseline can also be reviewed directly without creating an artificial revision.

`GET /projects/{project_id}/shots/{shot_id}/revisions/{revision_id}/image-eligibility` returns 409 `image_approval_required` for blocked versions. It does not generate images or enqueue work. No image provider is connected yet.

When adding the image worker, call `require_image_approval` under the shot lock before enqueueing and again before publishing results; pin jobs and image assets to the revision ID so a late result cannot overwrite a newer revision. Eligibility checks alone do not authorize a later job without revalidation.

