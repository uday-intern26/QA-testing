"""Jewellery placement validators for earring, necklace, bracelet, ring, and bangle."""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from app.cv.anchor_geometry import compare_reference, measure_placement
from app.cv.types import EarlobeAnchor, EarringAnchor, PlacementMeasurement, ReferenceComparison, ReferenceVector


class BodyAnchor(BaseModel):
    kind: str
    side: str | None = None
    x: float
    y: float
    confidence: float


class EarAnchor(BodyAnchor):
    kind: str = "ear"


class NeckAnchor(BodyAnchor):
    kind: str = "neck"


class WristAnchor(BodyAnchor):
    kind: str = "wrist"


class FingerAnchor(BodyAnchor):
    kind: str = "finger"


class JewelryPlacementValidator(ABC):
    jewelry_type: str

    @abstractmethod
    def validate(self, body_anchor, jewelry_anchor, *, config: dict) -> PlacementMeasurement:
        raise NotImplementedError

    def compare(self, reference: ReferenceVector | None, actual: PlacementMeasurement, config: dict) -> ReferenceComparison:
        return compare_reference(
            reference,
            actual,
            pass_threshold=config["pass_threshold"],
            fail_threshold=config["fail_threshold"],
        )


class EarringPlacementValidator(JewelryPlacementValidator):
    jewelry_type = "earring"

    def validate(self, body_anchor, jewelry_anchor, *, config: dict) -> PlacementMeasurement:
        earlobe = body_anchor if isinstance(body_anchor, EarlobeAnchor) else None
        earring = jewelry_anchor if isinstance(jewelry_anchor, EarringAnchor) else None
        return measure_placement(
            earlobe,
            earring,
            minimum_confidence=config["minimum_confidence"],
            pass_threshold=config["pass_threshold"],
            fail_threshold=config["fail_threshold"],
            zone_y_scale=config.get("zone_y_scale", 1.0),
        )


class AttachmentPlacementValidator(JewelryPlacementValidator):
    """Shared distance check for necklace, bracelet, ring, and bangle attachment points."""

    def __init__(self, jewelry_type: str) -> None:
        self.jewelry_type = jewelry_type

    def validate(self, body_anchor, jewelry_anchor, *, config: dict) -> PlacementMeasurement:
        body = body_anchor if isinstance(body_anchor, EarlobeAnchor) else None
        jewelry = jewelry_anchor if isinstance(jewelry_anchor, EarringAnchor) else None
        measurement = measure_placement(
            body,
            jewelry,
            minimum_confidence=config["minimum_confidence"],
            pass_threshold=config["pass_threshold"],
            fail_threshold=config["fail_threshold"],
            zone_y_scale=config.get("zone_y_scale", 1.0),
        )
        label = self.jewelry_type
        reason = measurement.reason
        if "Earlobe" in reason:
            reason = reason.replace("Earlobe", f"{label.capitalize()} body")
        if "Earring attachment" in reason:
            reason = reason.replace("Earring attachment", f"{label.capitalize()} attachment")
        if "earlobe placement zone" in reason:
            reason = reason.replace("earlobe placement zone", f"{label} placement zone")
        return measurement.model_copy(update={"reason": reason})


class NecklacePlacementValidator(AttachmentPlacementValidator):
    """Necklace uses shared attachment math; lay checks are applied only in the necklace runner path."""

    def __init__(self) -> None:
        super().__init__("necklace")


def validator_for(jewelry_type: str) -> JewelryPlacementValidator:
    if jewelry_type == "earring":
        return EarringPlacementValidator()
    if jewelry_type == "necklace":
        return NecklacePlacementValidator()
    if jewelry_type in {"bracelet", "ring", "bangle"}:
        return AttachmentPlacementValidator(jewelry_type)
    raise ValueError(
        f"Jewellery type '{jewelry_type}' is not supported. "
        "Use earring, necklace, bracelet, ring, or bangle."
    )
