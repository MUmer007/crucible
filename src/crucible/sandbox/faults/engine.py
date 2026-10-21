import random
import re

from crucible.sandbox.faults.types import FaultRule


def matches_path(rule_path: str, request_path: str) -> bool:
    # Treat rule_path as a regex if it has special chars, else exact match
    if any(c in rule_path for c in ['.', '*', '+', '?', '^', r'\$']):
        return bool(re.match(rule_path, request_path))
    return rule_path == request_path

def should_trigger_fault(rule: FaultRule, run_seed: int, call_n: int) -> bool:
    if rule.on_call is not None:
        return call_n in rule.on_call
    if rule.probability is not None:
        rng = random.Random(f"{run_seed}:{rule.id}:{call_n}")
        return rng.random() < rule.probability
    return True
