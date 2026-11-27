# Image quality and selective prediction controls

## Heuristic image quality

`ml.skin_image.quality.inspect_image_quality` reports image dimensions, mean luminance, clipped
pixel fraction and a simple Laplacian-variance detail score. It can flag low resolution, extreme
brightness/darkness, clipping and possible blur. Thresholds are configurable through
`ImageQualityPolicy`.

These are generic computer-vision heuristics, not clinically validated thresholds. They cannot
confirm that a photograph is a skin image, that it belongs to a supported modality, or that it is
suitable for diagnosis. Tune and validate thresholds on a representative, reviewed image set before
using them to reject user uploads. Do not silently alter image colors to make a photo pass.

## Confidence-based abstention

`ml.skin_image.selective.apply_abstention` accepts a matrix of class probability scores and a
minimum maximum-score threshold. Rows below the threshold return `None` rather than a class.
`selective_classification_metrics` reports coverage and metrics on accepted examples.

The maximum softmax score is not automatically calibrated and is not a probability of disease.
Thresholds must be selected on validation data using a predeclared coverage/risk objective, then
evaluated once on an untouched test set. Report both coverage and accepted-set performance; a
system that abstains on most difficult examples can otherwise look misleadingly strong.

## Calibration status

The offline training pipeline now fits scalar temperature scaling on validation logits only,
selects its abstention threshold on validation data, and evaluates calibration and selective
coverage on the untouched test partition. See `CALIBRATION.md` for the exact procedure.
This does not establish subgroup calibration or reliability on unsupported inputs.

## Not implemented yet

- Out-of-distribution detection validated against representative unsupported images
- Modality classification (dermoscopy versus ordinary phone photographs)
- Clinician-reviewed image quality thresholds
- External and subgroup validation

Do not interpret passing image checks or a high model score as diagnosis or medical certainty.
These controls are research scaffolding and are not approved for patient-facing use.
