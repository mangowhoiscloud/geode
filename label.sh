#!/bin/zsh
# judge↔human agreement 라벨링/리포트 래퍼
cd "$(dirname "$0")"
CMD="${1:-label}"   # label(기본) 또는 report / recalibrate
PYTHONPATH="$PWD" /Users/mango/workspace/geode/.venv/bin/python \
  -c "from plugins.petri_audit.cli_agreement import audit_agreement_app as a; a()" "$CMD"
