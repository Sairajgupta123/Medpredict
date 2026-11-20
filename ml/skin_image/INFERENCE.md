# Safety-gated skin-image inference helper

`ml.skin_image.inference.predict_skin_image` is an offline research helper that:

1. Applies the configured heuristic image-quality checks.
2. Rejects images that fail those checks before model execution.
3. Applies the same RGB, aspect-preserving resize and ImageNet normalization policy.
4. Runs the supplied model in inference mode.
5. Applies the supplied temperature and abstention threshold.
6. Returns either a research class, an uncertainty/abstention status, or a quality rejection.

## Caller responsibilities

The caller must supply:
- A trained model whose architecture and weights match the class mapping.
- The exact ordered class names stored with that model.
- A temperature fitted on validation logits only.
- A confidence threshold selected on validation data under a documented risk/coverage objective.
- A device supported by the installed PyTorch environment.

The function does not load untrusted model files, determine image modality, detect all out-of-distribution
inputs, or establish that a class is medically appropriate for a particular person. Quality thresholds
and confidence thresholds must be validated on representative data before any user-facing use.

## Output semantics

- `image_quality_rejected`: asks for a better image; no model prediction is run.
- `uncertain_abstained`: no class is returned because the score is below the supplied threshold.
- `research_prediction`: returns a class from the supplied training taxonomy only.

The returned score is not a disease probability or medical certainty. All results are research-only
and must not replace a clinician's assessment. This helper is not wired into the FastAPI application.
