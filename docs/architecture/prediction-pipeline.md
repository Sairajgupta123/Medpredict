# Prediction and symptom-review pipeline

## Current implementation status

MediPredict currently exposes a limited symptom phrase recognizer and an approved-catalog overlap comparison. Neither is a clinical prediction model.

### Text symptom flow

1. The browser sends symptom text and self-reported duration, severity and onset to the same-origin Next.js route.
2. The route validates the request and forwards it to `POST /api/v1/symptoms/normalize`.
3. The backend matches a curated phrase taxonomy in memory. It does not persist the submitted narrative.
4. Negated, historical and uncertain mentions are separated for human review. Unsupported residual wording is flagged.
5. The UI asks the user to confirm each recognized item. A phrase match is not treated as proof that a symptom is present.

### Approved catalog comparison

After the user explicitly confirms one or more symptoms as present:

1. The frontend sends only those symptom identifiers to `POST /api/symptoms/catalog-match`.
2. The same-origin Next.js route validates the list (1–20 unique identifiers) and proxies the request.
3. The backend verifies that each selected symptom is active and approved, with reviewer identity and review timestamp.
4. Disease entries, symptom entries and disease-symptom associations are all filtered to active, approved records with reviewer audit metadata.
5. Results show matched association counts and a catalog-overlap ratio. The ratio is only a description of catalog coverage for that disease entry.

The static phrase taxonomy used by the text recognizer and the database-backed, reviewer-governed disease catalog are separate data sources. A phrase-taxonomy identifier is eligible for matching only after a corresponding database symptom record and its disease associations have been created and approved with the required audit metadata. Until then, the endpoint rejects that identifier as not present in the approved catalog; this is an expected governance boundary, not evidence that the symptom is medically irrelevant.

The overlap ratio is **not** a disease probability, clinical risk score, confidence estimate, or measure of diagnostic accuracy. The matcher does not use the association relevance weight to imply calibrated risk. Diseases without an approved matched association are not returned. An empty result does not rule out disease.

### Privacy boundaries

- Free-text symptom narratives are sent only to the normalization endpoint and are not stored by that endpoint.
- The catalog comparison receives only confirmed symptom IDs, not the original narrative or the self-reported context fields.
- The comparison request is not stored as prediction history.
- Do not add request-body logging or analytics that capture symptom narratives.

### Clinical and governance constraints

- Draft, in-review, retired and inactive catalog records must never be exposed as matches.
- An approved status alone is insufficient: reviewer identity and review timestamp are required.
- This prototype must not claim diagnosis, disease probability, model accuracy, treatment guidance or clinical validation.
- Severe, rapidly worsening or worrying symptoms require professional assessment; the prototype must never be used to decide whether care is necessary.

### Skin-image intake security foundation

The backend now contains a standalone validation utility at `backend/app/services/skin_image_validation.py`. It checks actual decoded image format rather than trusting filenames, enforces an 8 MiB payload limit, a 6,000-pixel edge limit and a 20-megapixel limit, rejects animated/multi-frame files, and re-encodes accepted JPEG, PNG and WebP images from raw pixels to remove EXIF, ICC and textual metadata. Pillow is a backend dependency for this processing.

An additional advisory quality helper reports basic capture indicators (small dimensions, very dark or overexposed pixels, and near-uniform/low-contrast images). These are technical warnings only; they are not a clinical quality score, do not establish that a lesion is visible, and must not be used to diagnose or deny care.\n\nThis utility is not an HTTP upload endpoint and does not store files. It is not yet connected to prediction history or model inference. Upload routes remain intentionally disabled until private object storage, authenticated upload controls, explicit image-processing consent, retention rules, deletion verification, request-size enforcement and operational rate limits are implemented. The utility does not establish that an image is clinically suitable or support a diagnosis.



### Private storage adapter boundary

`backend/app/services/skin_image_storage.py` defines a narrow private-storage protocol and a default adapter that fails closed. No cloud bucket, local disk fallback, public URL, or upload route is configured. Object keys are generated from server-side image UUIDs and safe extensions; they do not contain account identifiers or original filenames. A production adapter must provide private-only access, encryption at rest, TLS, least-privilege credentials, no public object URLs, and idempotent deletion. Retrieval must only be called after application-level ownership checks. The protocol is an integration contract, not proof that a storage provider has been configured or audited.

Before enabling image upload, the next implementation stages must add a separate image-processing consent purpose and immutable consent events, persist only metadata after successful private object creation, handle partial failures with compensating deletion, implement verified deletion before acknowledging revocation, and test cross-user access isolation. Retention expiry and operational deletion reconciliation are also required.

## Not implemented yet

- A clinically validated disease-risk model and its external validation evidence.
- A curated, source-cited and clinically reviewed disease/symptom knowledge base with adequate coverage.
- Model calibration, subgroup performance, bias evaluation and prospective evaluation.
- Skin-image classification, dataset provenance, image-quality checks, secure object storage and deletion lifecycle.
- Clinician-facing review workflows for prediction outputs.

These capabilities require suitable data, documented approvals, validation and privacy controls before any clinical-facing use.


### Image consent and deletion lifecycle

Image consent is separated into `skin_image_processing` (permission to process an uploaded image for the immediate request) and `skin_image_history` (permission to retain an image and its associated history). These are distinct from `prediction_history` for text. The consent event table accepts the separate purposes; this does not itself enable image processing or imply consent has been granted.

Image metadata now tracks `unknown`, `pending_upload`, `stored`, `deletion_pending`, `deleted`, or `failed` storage states. Existing records migrate to `unknown` rather than being assumed to exist in configured private storage. The deletion service records `deletion_pending` and commits that marker before calling the storage adapter. It removes database history only after storage confirms deletion. If storage fails, the history record remains available for retry; if storage deletion succeeds but a later database operation fails, the retry repeats an idempotent object deletion. Unknown or incomplete storage states are blocked for manual reconciliation.

The authenticated image-intake endpoint is implemented and remains fail-closed unless bucket and region settings are supplied. It requires separate processing and history consent, validates and sanitizes the uploaded image, stores it through the private adapter, and exposes no object key or URL. The public history-delete route now resolves the configured adapter and removes the private object before deleting the database history record. Image-history consent revocation similarly deletes the object first, then records the revocation; a failed deletion leaves a durable pending marker and consent remains active until retry succeeds.


### Explicit image retention scheduling

Migration `0018_skin_image_retention` adds nullable `retention_expires_at` and `retention_policy_version` metadata with an index for expiry lookups. No default duration is imposed: a caller must provide a timezone-aware future expiry and a policy version, and the owner must have separately granted `skin_image_history` consent. The service only schedules retention for an image already confirmed as `stored`.

`list_expired_skin_image_records` returns bounded batches of due image records, including deletion-pending records so failed operations can be retried. `purge_expired_skin_image_records` deletes private objects in a bounded batch, preserves prediction/consent audit rows, records a revoked image-history event after successful expiry deletion, and leaves failed objects pending for a later run. The executable worker is `python -m app.workers.skin_image_retention`; schedule it with the deployment platform's job scheduler. Configure a single non-overlapping worker schedule, alert on non-zero failure counts, and approve the retention duration/policy before scheduling.


### Private S3-compatible object storage adapter

The backend now includes an opt-in `S3PrivateSkinImageStorage` adapter. It accepts an injected SDK client and a bucket name; it does not create credentials, select a bucket, or activate itself at application startup. The client factory enforces TLS certificate verification, HTTPS for custom endpoints, and SigV4. Bucket writes explicitly request server-side encryption (AES256 by default or KMS with a required key ID), omit public ACLs, and store a SHA-256 integrity value. Reads are size-bounded and verify the stored digest. Object keys are restricted to the server-generated opaque image-key pattern; no public or presigned URL functionality is provided.

The backend dependency list now includes boto3. Unit tests use an in-memory fake S3 client and do not contact a cloud account. Before production activation, operations must create a private bucket, enforce block-public-access and restrictive bucket policies, enable versioning/object-lock only if the approved retention policy requires it, configure encryption and IAM least privilege, supply secrets through deployment secret management, and test the actual provider account. The adapter is wired into the authenticated image-intake endpoint, history deletion, consent revocation and the scheduled retention worker only when bucket and region settings are present. The application code and CI fake-client tests do not verify a real cloud account, bucket policy, IAM permissions or provider-side retention controls; those remain deployment acceptance checks.

## Human skin-image review workflow

Stored skin images can be assigned by an administrator to an active, email-verified account with the reviewer role:

- POST /api/v1/skin-images/review/{prediction_id}/assign — administrator assigns or reassigns a stored image with an 8–1,000 character operational reason.
- GET /api/v1/skin-images/review/queue — reviewers see only their assigned items; administrators can inspect all assigned items.
- GET /api/v1/skin-images/review/{prediction_id}/image — only the assigned reviewer or an administrator can retrieve the private image while processing consent remains active.
- POST /api/v1/skin-images/review/{prediction_id}/decision — assigned reviewer or administrator records capture_adequate or unable_to_assess, with an audit reason.
- GET /api/v1/skin-images/review/{prediction_id}/events — assigned reviewer and administrators can inspect the append-only assignment/review event history.

The workflow is strictly a technical capture-quality review. capture_adequate does not mean a lesion is benign, malignant, or clinically assessable. No diagnosis, disease label, probability, treatment advice, or clinical interpretation is accepted or produced. Processing consent is checked before queue inclusion, image retrieval, assignment, and review decisions. Reviewers must be explicitly provisioned and verified operationally; the role and email-verification flags alone do not establish clinical qualifications. Administrators are responsible for verifying reviewer credentials and scope before assignment.

Review audit events preserve opaque prediction/image UUID references without foreign keys to the user-history rows, so deleting an image history item does not erase the assignment/review audit trail. The audit stores actor, assignee, event, limited outcome, reason, and timestamp; it does not store image bytes or a public image URL. The reviewer console provides assignment and technical review controls. The access and review audit page lists actor identity, role, event type, reason and timestamp without exposing image bytes or object keys. Production reviewer qualification and operational governance still require organization-level verification.


### Dedicated skin-image reviewer permissions

A general reviewer role or a catalog-review scope does not grant access to patient images. Administrators must grant a separate `skin_image` reviewer scope through `POST /api/v1/admin/reviewer-scopes`. A skin-image scope must use the exact prediction UUID as `scope_key`; broad or null-key image scopes are rejected. This enforces least-privilege access per submission.

The image-review assignment endpoint requires that scope in addition to an active, verified reviewer account. Queue inclusion, private image retrieval, review decisions and audit-history access re-check the active scope. Revoking the scope immediately blocks further reviewer access. When an image is reassigned, the previous reviewer's exact image scope is automatically revoked and an immutable scope event is recorded. The admin review screen grants an exact-image scope before assignment; it does not grant blanket image access.

The scope grant is an application authorization control, not proof of clinical credentials. Administrators must separately verify reviewer qualifications, contractual authorization, training and permitted purpose before granting access. Access logging and audit retention should be monitored under the deployment's privacy policy.


Successful image delivery is also recorded as an `image_accessed` audit event with the authenticated actor, assigned reviewer, submission references, reason and timestamp. Failed or unauthorized requests are not represented as successful image views. The audit event contains no image bytes, public URL or clinical interpretation.

### Separate consent for human image review

Separate `skin_image_processing`, `skin_image_history`, and `skin_image_review` consent purposes are recorded with independent policy versions. The intake endpoint requires all three explicit choices. Human-review queue access, assignment, decisions and private reviewer image retrieval require active processing and human-review consent. The owner can revoke human-review consent at `POST /api/v1/skin-images/{prediction_id}/revoke-review-consent`; this immediately revokes exact-image reviewer scopes while retaining the minimal audit trail. Image-history consent remains a separate control for owner retrieval and retention.


The multipart intake request includes `processing_consent`, `history_consent`, `review_consent` and the matching `processing_policy_version`, `history_policy_version`, and `review_policy_version` fields. Submissions created before this separate review-consent requirement do not become reviewable automatically; they need a fresh, explicit owner consent event before any human reviewer can access them. A missing review-consent event is treated as no consent.


### Skin-image review audit feed

- `GET /api/v1/skin-images/review/audit?limit=100&offset=0` returns a bounded audit feed. Administrators can inspect all skin-image review events. Reviewers can inspect only events where they were the actor or the assigned reviewer, including their own historical assignment events after reassignment.
- The feed identifies the actor using the account display name or email and includes actor role, event, opaque submission reference, assigned reviewer reference, outcome, recorded reason and timestamp.
- The frontend page is `/review/skin-images/audit`, linked from the skin-image reviewer queue. It displays metadata only; it never retrieves or embeds image bytes.
- Pagination is bounded to 1–200 rows and offset 0–10,000. The feed is newest-first. It is an operational view, not a tamper-proof external compliance archive.
- `image_accessed` is recorded only after private object retrieval and integrity/format checks succeed. It proves successful server-side retrieval, not that a human visually inspected the entire image.


### Owner-facing technical image-review status

Authenticated owners can request `GET /api/v1/skin-images/{prediction_id}/review-status` for their own skin-image submission. The endpoint returns only a small status vocabulary (awaiting review, assigned, technically reviewed, unable to assess, unavailable, or review permission withdrawn), a status timestamp where applicable, and explicit false flags for clinical interpretation and disease prediction. Cross-user access returns not found. Reviewer identities, assignment reasons, audit events, storage keys, image bytes, reviewer notes, and diagnostic fields are never included. The owner image-history page displays this status separately from the prediction record status. If review consent has been revoked, the endpoint reports that permission was withdrawn without disclosing further review details.
