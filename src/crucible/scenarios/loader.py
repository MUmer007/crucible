from pathlib import Path

import yaml
from pydantic import ValidationError

from crucible.scenarios.schema import Scenario, compute_scenario_version


def load_scenario(file_path: str | Path) -> Scenario:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Scenario file not found: {path}")
    
    with open(path, "r", encoding="utf-8") as f:
        raw_content = f.read()
    
    try:
        data = yaml.safe_load(raw_content)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in scenario file: {e}")
    
    if not isinstance(data, dict):
        raise ValueError("Scenario file must contain a YAML dictionary at the root")  # noqa: TRY004
    
    # Compute version hash before validation
    version_hash = compute_scenario_version(data)
    
    try:
        scenario = Scenario(**data)
        scenario.scenario_version = version_hash
        return scenario
    except ValidationError as e:
        # Pydantic v2 provides detailed errors naming the exact field
        raise ValueError(f"Invalid scenario schema in {path.name}:\n{e}")
