"""Scenario_Registry: UI labels and default seeds. Labels are UI-only and never written to factory.db."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RegistryEntry:
    dataset_id: str
    scenario_key: str
    label: str
    description: str
    default_seed: int


_ENTRIES: tuple[RegistryEntry, ...] = (
    RegistryEntry("ds-00", "baseline", "Baseline – Normal Operation",
                  "One normal 8-hour shift on Line A with about 2% EOL defects on both testers.", 1),
    RegistryEntry("ds-01", "a", "Scenario A – EOL Tester Drift",
                  "EOL Tester B defect rate climbs during the shift while Tester A stays normal.", 2),
    RegistryEntry("ds-02", "b", "Scenario B – Manufacturing Process Defect",
                  "Both EOL testers report more defects in the second half of the shift.", 3),
    RegistryEntry("ds-03", "c", "Scenario C – Insufficient Evidence",
                  "EOL Tester B shows a higher defect rate, but key verification data is missing.", 6),
)
DATASET_IDS = tuple(e.dataset_id for e in _ENTRIES)
SCENARIO_KEYS = tuple(e.scenario_key for e in _ENTRIES)


class RegistryError(KeyError):
    def __str__(self) -> str:  # KeyError quotes its message otherwise
        return str(self.args[0])


def list_entries() -> list[RegistryEntry]:
    return list(_ENTRIES)


def get_entry(dataset_id: str) -> RegistryEntry:
    for e in _ENTRIES:
        if e.dataset_id == dataset_id:
            return e
    raise RegistryError(f"unknown dataset id {dataset_id!r}; valid: {', '.join(DATASET_IDS)}")


def get_entry_by_key(key: str) -> RegistryEntry:
    for e in _ENTRIES:
        if e.scenario_key == key:
            return e
    raise RegistryError(f"unknown scenario key {key!r}; valid: {', '.join(SCENARIO_KEYS)}")
