# MediPredict Reviewed Medical Knowledge Base

This directory is the editorial workspace for general health education content. It is intentionally
not populated with disease-specific medical advice yet. No clinical content should be published
until a qualified reviewer has verified the source and the exact wording.

## Content types

- `general_care`: low-risk, general self-care information supported by a reviewed source.
- `precautions`: practical risk-reduction information.
- `lifestyle`: general lifestyle information with appropriate caveats.
- `diet`: general nutrition information; avoid universal or restrictive diet claims.
- `when_to_seek_care`: symptoms or situations that warrant clinician assessment.
- `emergency_signs`: emergency warning signs with explicit local escalation instructions.

## Required editorial workflow

1. Register the source in `source_register.json` with its publisher, URL, version/date, access date,
   evidence type, license/usage notes, and a stable source identifier.
2. Verify that the source is authoritative, current, relevant to the intended population and usable
   under its license. A source URL alone is not evidence of permission to reproduce its text.
3. Draft a short paraphrase; do not copy large portions of copyrighted source material.
4. Record the intended audience, locale, scope, exclusions, review date, and validity window.
5. Obtain qualified clinical review for factual accuracy, urgency, contraindications and wording.
6. Obtain separate editorial and privacy review where relevant.
7. Store approved content in the backend with reviewer identity, review timestamp, source links,
   version, and validity dates. Only the backend's approved, active, source-backed endpoint may
   expose it.
8. Re-review on the source's update, an expiry date, a safety report, or a scheduled review date.

## Non-negotiable safety rules

- This knowledge base provides education, not diagnosis or individualized treatment.
- Do not include prescriptions, medication dosages, or instructions to start/stop medicines.
- Do not invent disease-specific symptom associations, cures, prevention claims, or outcome claims.
- Do not use AI-generated text as its own evidence or reviewer.
- Do not infer an emergency is absent because a symptom was not selected.
- Keep emergency guidance conservative, reviewed, and localized before production release.
- Include an explicit clinician-care pathway and a clear disclaimer.
- Do not place patient records, identifiable health information, credentials, or restricted source
  documents in this repository.

## Status

The initial source register is empty. The backend schema and read-only publication API are scaffolds;
there is no approved medical content and the endpoint should return empty lists until a complete
human review and publication workflow exists.
