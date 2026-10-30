#!/usr/bin/env python3
"""Extract the actual CRE handler result from CLI stdout; never invent a result."""
import json
from pathlib import Path
import re
import sys


def extract(text):
    text = re.sub(r'\x1b\[[0-9;]*m', '', text)
    marker = 'Workflow Simulation Result:'
    if text.count(marker) != 1:
        raise ValueError('expected exactly one successful Workflow Simulation Result')
    value, _ = json.JSONDecoder().raw_decode(text.split(marker, 1)[1].lstrip())
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict) or value.get('check') != 'chainlink-cre-market-evidence' or 'sha256' not in value:
        raise ValueError('not a Convergence Desk CRE result')
    return value


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('usage: python3 cre/extract_result.py simulate.log simulate_output.json')
    result = extract(Path(sys.argv[1]).read_text())
    Path(sys.argv[2]).write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
