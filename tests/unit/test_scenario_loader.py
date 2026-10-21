import tempfile
from pathlib import Path

import pytest

from crucible.scenarios.loader import load_scenario


def test_invalid_scenario_rejects_unknown_fields():
    yaml_content = '''
id: test-scenario
version_note: "test"
description: "Test scenario"
tags: ["test"]
seed: 1
runs: 1
task: "Do something"
seed_data: "fixtures/test.yaml"
budget:
  max_requests: 10
  max_seconds: 60
unknown_field_that_should_fail: "this is a typo"
'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
        f.write(yaml_content)
        temp_path = f.name
    
    try:
        with pytest.raises(ValueError) as exc_info:
            load_scenario(temp_path)
        
        # Verify the error message names the offending field
        error_msg = str(exc_info.value).lower()
        assert "unknown_field_that_should_fail" in error_msg or "extra inputs are not permitted" in error_msg
    finally:
        Path(temp_path).unlink()

def test_valid_scenario_loads_with_version():
    yaml_content = '''
id: test-scenario
version_note: "test"
description: "Test scenario"
tags: ["test"]
seed: 1
runs: 1
task: "Do something"
seed_data: "fixtures/test.yaml"
budget:
  max_requests: 10
  max_seconds: 60
'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False, encoding='utf-8') as f:
        f.write(yaml_content)
        temp_path = f.name
    
    try:
        scenario = load_scenario(temp_path)
        assert scenario.id == "test-scenario"
        # Verify a 16-character hex hash was generated
        assert len(scenario.scenario_version) == 16
        assert all(c in "0123456789abcdef" for c in scenario.scenario_version)
    finally:
        Path(temp_path).unlink()
