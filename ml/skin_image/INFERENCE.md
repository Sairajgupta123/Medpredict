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

## Checkpoint integrity

Before constructing a model for inference, call
`ml.skin_image.inference.validate_skin_checkpoint(checkpoint, metadata)` with the
loaded checkpoint dictionary and the parsed `model_metadata.json`. The validator checks
the ordered class list and exact index mapping, supported architecture/variant, image size,
normalization policy, experiment-configuration SHA-256 digest, calibration values, and the
validation-only threshold-selection marker. It also verifies non-empty numeric weight tensors and
rejects empty, non-numeric, or non-finite tensor values. Metadata claiming clinical validation or
a non-research intended use is rejected. Use the returned settings rather than separately retyping
class names, image size, temperature, or confidence threshold. This is structural validation; it
does not prove that tensor keys and shapes match a particular architecture. The model's
`load_state_dict` remains responsible for architecture-specific key and shape compatibility.

This is an integrity and consistency check, not a signature or proof that an artifact is
trustworthy. Only load checkpoint files from controlled, trusted storage; do not load
user-uploaded model files.

## Experiment output safety

The skin-image trainer refuses to start when any expected output from the selected architecture
already exists in the output directory: the experiment configuration, best checkpoint, model
metadata, or experiment report. Use a fresh output directory for each run and explicitly archive
older experiment evidence before reusing a location. The trainer does not silently replace prior
checkpoints or reports.
