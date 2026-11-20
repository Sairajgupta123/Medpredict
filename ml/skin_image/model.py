"""MobileNetV3 model factory for offline skin-image experiments."""

from __future__ import annotations


def build_mobilenet_v3(
    num_classes: int,
    *,
    variant: str = "large",
    pretrained: bool = False,
):
    """Build a MobileNetV3 classifier.

    Pretrained weights are opt-in because requesting them may download external files.
    """
    if num_classes < 2:
        raise ValueError("num_classes must be at least 2")
    try:
        from torch import nn
        from torchvision.models import (
            MobileNet_V3_Large_Weights,
            MobileNet_V3_Small_Weights,
            mobilenet_v3_large,
            mobilenet_v3_small,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Install the optional skin dependencies from ml/requirements-skin.txt"
        ) from exc

    if variant == "large":
        weights = MobileNet_V3_Large_Weights.DEFAULT if pretrained else None
        network = mobilenet_v3_large(weights=weights)
    elif variant == "small":
        weights = MobileNet_V3_Small_Weights.DEFAULT if pretrained else None
        network = mobilenet_v3_small(weights=weights)
    else:
        raise ValueError("variant must be 'large' or 'small'")

    input_features = network.classifier[-1].in_features
    network.classifier[-1] = nn.Linear(input_features, num_classes)
    return network
