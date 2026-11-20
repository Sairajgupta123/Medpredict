# Skin-image dataset assessment

**Status:** Research assessment only. No dataset has been approved for training or patient-facing use.

## Why modality matters

A model trained on dermatoscopic close-up images must not be represented as a general model for
ordinary phone photographs of rashes, infections, wounds, or other visible skin changes.
Image acquisition, framing, lighting, skin tone coverage, clinical label definitions and intended
diagnostic task differ.

## Candidate comparison

| Candidate | Image type and scale | Grouping and labels | Key limitations / decision |
|---|---|---|---|
| HAM10000 | 10,015 dermatoscopic images; seven pigmented-lesion categories in the original data descriptor | Lesion metadata is available; ISIC archive currently lists 11,720 images, 8,838 specified lesions and zero specified patients | Useful as a dermoscopy benchmark only. Strong class imbalance and multi-source acquisition. Do not assume patient-level split is possible from the archive patient field. |
| PAD-UFES-20 | 2,298 smartphone clinical images, 1,641 lesions, 1,373 patients; six diagnostic categories | Patient and lesion structure are described in the dataset paper | More aligned with smartphone capture, but small and still limited to its defined lesion categories. Check original download terms, metadata availability and label mapping before use. |

## Source review

### HAM10000

- Original data descriptor: https://doi.org/10.1038/sdata.2018.161
- Original descriptor reports 10,015 dermatoscopic images and a class distribution heavily dominated by melanocytic nevi.
- The original paper reports HAM10000 under CC BY-NC 4.0. Verify the exact archive release and each included source's terms before redistribution or use.
- ISIC archive collection record: https://api.isic-archive.com/collections/212/
- ISIC challenge data and attribution instructions: https://challenge.isic-archive.com/data/
- The archive currently lists 11,720 images and 8,838 specified lesions, but zero specified patients. Do not claim patient-level grouping from that archive record alone.

### PAD-UFES-20

- Original paper: https://doi.org/10.1016/j.dib.2020.106221
- PubMed Central full text: https://pmc.ncbi.nlm.nih.gov/articles/PMC7479321/
- Paper describes 2,298 smartphone clinical images from 1,373 patients and 1,641 lesions, across six diagnostic categories.
- The article is open access, but the exact dataset download terms and any restrictions on the image files must be verified at the authoritative download location. A third-party mirror's license label is not sufficient evidence of the original dataset license.

## Provisional recommendation

1. Treat PAD-UFES-20 as the first candidate to investigate for a smartphone-photo research prototype.
2. Treat HAM10000 as a separate dermoscopy-only benchmark, never as interchangeable with phone photos.
3. Do not merge the datasets into one label space without a clinically reviewed mapping and acquisition-domain analysis.
4. Obtain exact source files, metadata and terms from the authoritative providers before training.
5. Do not commit image files, metadata containing patient-level identifiers, or trained weights to Git.

## Required intake gates

- [ ] Authoritative source and exact release/version recorded
- [ ] Dataset license and permitted use reviewed
- [ ] Privacy, ethics and redistribution conditions reviewed
- [ ] Image modality and intended input population documented
- [ ] Label definitions and diagnostic provenance reviewed
- [ ] Patient and lesion grouping fields inspected
- [ ] Patient-level and lesion-level overlap prevented across splits
- [ ] Duplicate file hashes and corrupt image audit completed
- [ ] Per-class and subgroup counts reviewed
- [ ] Skin-tone, age, sex, device and acquisition coverage limitations documented
- [ ] Clinician review of label mapping and error analysis planned

## Model comparison plan (not yet run)

Candidate backbones: MobileNetV3, ResNet50 and EfficientNetB0. Compare them using the same
patient-grouped partitions, training budget, image resolution policy and augmentation policy.
Choose based on macro-F1, per-class sensitivity/recall, specificity where appropriate,
balanced accuracy, calibration, confidence/abstention behavior, subgroup performance,
latency and model size—not accuracy alone.

No architecture is selected as a winner before the controlled experiment.

## Safety boundary

This project is not a diagnostic device. Predictions must be limited to the supported image
modality and dataset classes. The interface must say when an image is blurry, unsupported,
out of distribution or too uncertain and must not return a confident disease label in those
cases. Severe or rapidly worsening symptoms require professional care regardless of model output.
