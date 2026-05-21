from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import Any


__all__ = [
    "SensitivityLevel",
    "DataTag",
    "ClassificationRule",
    "DataClassifier",
]


class SensitivityLevel(enum.Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
    CRITICAL = "critical"


@dataclass
class DataTag:
    name: str
    sensitivity: SensitivityLevel
    regulations: set[str] = field(default_factory=set)


@dataclass
class ClassificationRule:
    name: str
    field_pattern: str
    tags: list[DataTag]
    auto: bool = True


_BOUNDARY = r"(?:^|_|\b)"

_DEFAULT_RULES: list[ClassificationRule] = [
    ClassificationRule("email", rf"(?i){_BOUNDARY}email(?:$|_|\b)", [DataTag("email", SensitivityLevel.CONFIDENTIAL, {"gdpr"})]),
    ClassificationRule("ssn", rf"(?i){_BOUNDARY}ssn(?:$|_|\b)", [DataTag("ssn", SensitivityLevel.RESTRICTED, {"hipaa", "gdpr"})]),
    ClassificationRule("mrn", rf"(?i){_BOUNDARY}mrn(?:$|_|\b)", [DataTag("mrn", SensitivityLevel.RESTRICTED, {"hipaa"})]),
    ClassificationRule("phone", rf"(?i){_BOUNDARY}phone(?:$|_|\b)", [DataTag("phone", SensitivityLevel.CONFIDENTIAL, {"gdpr"})]),
    ClassificationRule("address", rf"(?i){_BOUNDARY}address(?:$|_|\b)", [DataTag("address", SensitivityLevel.CONFIDENTIAL, {"gdpr"})]),
    ClassificationRule("credit_card", rf"(?i){_BOUNDARY}credit_card(?:$|_|\b)", [DataTag("credit_card", SensitivityLevel.RESTRICTED, {"pci"})]),
    ClassificationRule("password", rf"(?i){_BOUNDARY}password(?:$|_|\b)", [DataTag("password", SensitivityLevel.CRITICAL, set())]),
    ClassificationRule("token", rf"(?i){_BOUNDARY}token(?:$|_|\b)", [DataTag("token", SensitivityLevel.RESTRICTED, set())]),
    ClassificationRule("api_key", rf"(?i){_BOUNDARY}api_key(?:$|_|\b)", [DataTag("api_key", SensitivityLevel.CONFIDENTIAL, set())]),
    ClassificationRule("health_record", rf"(?i){_BOUNDARY}health_.+", [DataTag("health_data", SensitivityLevel.RESTRICTED, {"hipaa"})]),
    ClassificationRule("medical_record", rf"(?i){_BOUNDARY}medical_.+", [DataTag("medical_data", SensitivityLevel.RESTRICTED, {"hipaa"})]),
    ClassificationRule("diagnosis", rf"(?i){_BOUNDARY}diagnosis(?:$|_|\b)", [DataTag("diagnosis", SensitivityLevel.RESTRICTED, {"hipaa"})]),
    ClassificationRule("treatment", rf"(?i){_BOUNDARY}treatment(?:$|_|\b)", [DataTag("treatment", SensitivityLevel.RESTRICTED, {"hipaa"})]),
]


_SENSITIVITY_ORDER: list[SensitivityLevel] = [
    SensitivityLevel.PUBLIC,
    SensitivityLevel.INTERNAL,
    SensitivityLevel.CONFIDENTIAL,
    SensitivityLevel.RESTRICTED,
    SensitivityLevel.CRITICAL,
]

_SENSITIVITY_RANK: dict[SensitivityLevel, int] = {
    level: idx for idx, level in enumerate(_SENSITIVITY_ORDER)
}


class DataClassifier:
    def __init__(self) -> None:
        self._rules: list[ClassificationRule] = list(_DEFAULT_RULES)

    def classify_field(self, field_name: str) -> list[DataTag]:
        tags: list[DataTag] = []
        for rule in self._rules:
            if re.search(rule.field_pattern, field_name):
                tags.extend(rule.tags)
        return tags

    def classify_dict(self, data: dict[str, Any]) -> dict[str, list[DataTag]]:
        return {key: self.classify_field(key) for key in data}

    def get_sensitivity(self, data: dict[str, Any]) -> SensitivityLevel:
        max_rank = -1
        result = SensitivityLevel.PUBLIC
        for tags in self.classify_dict(data).values():
            for tag in tags:
                rank = _SENSITIVITY_RANK.get(tag.sensitivity, 0)
                if rank > max_rank:
                    max_rank = rank
                    result = tag.sensitivity
        return result

    def add_rule(self, rule: ClassificationRule) -> None:
        self._rules.append(rule)

    def get_regulations(self, data: dict[str, Any]) -> set[str]:
        regulations: set[str] = set()
        for tags in self.classify_dict(data).values():
            for tag in tags:
                regulations.update(tag.regulations)
        return regulations
