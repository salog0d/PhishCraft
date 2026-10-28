#!/usr/bin/env bash
# Start the PhishCraft observability stack:
#   1. the container suite (prometheus, alertmanager, grafana,
#      node-exporter, runs-exporter)
#   2. the GPU exporter on the host (needs nvidia-smi)
#
# The MailHog alert sink is separate: `docker compose up -d` at the repo root.
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose -f monitoring/compose.yaml up -d

if ! curl -sf http://localhost:9400/metrics >/dev/null 2>&1; then
    nohup venv/bin/python monitoring/gpu_exporter.py \
        >> /tmp/phishcraft_gpu_exporter.log 2>&1 &
    echo "gpu exporter started (:9400)"
else
    echo "gpu exporter already running (:9400)"
fi

echo
echo "grafana:       http://localhost:3000  (admin / admin)"
echo "prometheus:    http://localhost:9099"
echo "alertmanager:  http://localhost:9093"
echo "alerts inbox:  http://localhost:8025  (MailHog)"
