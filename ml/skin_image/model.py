"""Model factories for controlled skin-image architecture comparisons.

All architectures use ImageNet weights only when explicitly requested. Selecting pretrained
weights may download external artifacts; keep downloaded weights and checkpoints out of Git.
"""

from __future__ import annotations


def build_skin_classifier(
    num_classes: int,
    *,
    architecture: str = "mobilenet_v3",
    variant: str = "large",
    pretrained: bool = False,
):
    """Build MobileNetV3, ResNet50 or EfficientNet-B0 with a task-specific head."""
    if num_classes < 2:
        raise ValueError("num_classes must be at least 2")
    try:
        from torch import nn
        from torchvision import models
    except ImportError as exc:
        raise RuntimeError(
            "Install the optional skin dependencies from ml/requirements-skin.txt"
        ) from exc

    if architecture == "mobilenet_v3":
        if variant == "large":
            weights = models.MobileNet_V3_Large_Weights.DEFAULT if pretrained else None
            network = models.mobilenet_v3_large(weights=weights)
        elif variant == "small":
            weights = models.MobileNet_V3_Small_Weights.DEFAULT if pretrained else None
            network = models.mobilenet_v3_small(weights=weights)
        else:
            raise ValueError("MobileNetV3 variant must be 'large' or 'small'")
        input_features = network.classifier[-1].in_features
        network.classifier[-1] = nn.Linear(input_features, num_classes)
        return network

    if variant != "default":
        raise ValueError("ResNet50 and EfficientNet-B0 use variant='default'")

    if architecture == "resnet50":
        weights = models.ResNet50_Weights.DEFAULT if pretrained else None
        network = models.resnet50(weights=weights)
        network.fc = nn.Linear(network.fc.in_features, num_classes)
        return network

    if architecture == "efficientnet_b0":
        weights = models.EfficientNet_B0_Weights.DEFAULT if pretrained else None
        network = models.efficientnet_b0(weights=weights)
        network.classifier[-1] = nn.Linear(
            network.classifier[-1].in_features, num_classes
        )
        return network

    raise ValueError(
        "architecture must be 'mobilenet_v3', 'resnet50' or 'efficientnet_b0'"
    )


def build_mobilenet_v3(
    num_classes: int,
    *,
    variant: str = "large",
    pretrained: bool = False,
):
    """Backward-compatible MobileNetV3 model factory."""
    return build_skin_classifier(
        num_classes,
        architecture="mobilenet_v3",
        variant=variant,
        pretrained=pretrained,
    )
