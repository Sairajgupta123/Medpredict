# Dataset provenance registry

The candidate assessment documents describe research leads, not approved datasets. Before any
dataset is downloaded or used, create or update a record in registry.example.json (copy it to a
private registry file if additional internal notes are needed).

## Required evidence

Record the exact source URL and release, retrieval date, modality/acquisition domain, dataset-level
license, permission to download/modify/train/redistribute, privacy review, label review, grouping
fields and qualified reviewer sign-off. The license of a research paper or a mirror is not assumed
to grant rights to the underlying image files.

## Run the technical registry check

From the repository root:

```bash
python -m ml.datasets.registry --registry ml/datasets/registry.example.json
```

The validator checks metadata completeness and controlled review-state values. It intentionally
always reports training_eligible=false and automatic_approval=false. A human governance process
must separately approve research use. This tool does not interpret legal terms or validate clinical
quality.

Never store patient identifiers, private credentials, access tokens or restricted dataset files in
this registry or Git.
