# Model card: skin-image research baseline

**Status:** Dataset not approved; no model trained; not approved for patient-facing use.

## Intended task

Research classification of skin-lesion images into a specifically documented dataset label set.
The supported image acquisition modality must be stated explicitly (for example, dermatoscopic
images versus ordinary smartphone clinical photographs). These modalities are not interchangeable.

## Dataset and provenance

- Dataset: Not selected
- Version/release: Not selected
- Authoritative source: Not verified
- License and permitted use: Pending review
- Image modality: Not selected
- Label definitions and diagnostic provenance: Pending
- Patient-level grouping availability: Pending
- Lesion-level grouping availability: Pending
- Demographic and skin-tone coverage: Pending
- Dataset audit: Not run

## Candidate backbones

MobileNetV3, ResNet50 and EfficientNetB0 are candidates for a controlled comparison. No architecture
has been selected as best and no performance metrics are available.

## Evaluation requirements

- Patient-level split; keep all images and lesions belonging to a patient in one partition.
- If patient identifiers are unavailable, document that limitation and do not claim patient-level
  independence. Lesion-level grouping alone is not an adequate substitute for patient-level split.
- Deduplicate exact image content and inspect conflicting labels.
- Report per-class sample counts, macro-F1, per-class sensitivity/recall, specificity where
  appropriate, balanced accuracy, confusion matrix, calibration, abstention coverage and subgroup
  performance.
- Evaluate image quality failures, unsupported modalities and out-of-distribution inputs.
- Reserve an independent external test set where a suitable source is available.

## Known risks

- Dataset class imbalance and source/device bias
- Dermatoscopic-to-phone-photo domain shift
- Limited representation of skin tones, age groups and geographic populations
- Multiple images of the same lesion or patient
- Imperfect or heterogeneous diagnostic labels
- Shortcut learning from rulers, backgrounds, markers or acquisition artifacts

## Required controls before API integration

- Approved source, license and privacy review
- Clinician-reviewed label taxonomy and image inclusion policy
- Patient-level leakage-resistant evaluation
- Calibrated uncertainty and abstention thresholds
- Image-quality and unsupported-input rejection
- External validation and subgroup error analysis
- Versioned preprocessing, weights, model card and rollback plan
- Clear user-facing limitations and clinician escalation guidance

## Approval

- Dataset/legal reviewer: Pending
- Clinical/domain reviewer: Pending
- ML evaluation reviewer: Pending
- Privacy/security reviewer: Pending
- API integration approval: Not granted
