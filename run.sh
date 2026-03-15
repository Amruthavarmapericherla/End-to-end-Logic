#!/usr/bin/env bash
set -euo pipefail

# Start container with auto-restart on host reboot.
# Uses --restart=always as requested.
IMAGE_NAME="${IMAGE_NAME:-fix-commitment}"
CONTAINER_NAME="${CONTAINER_NAME:-scrapping}"

docker run -d \
  --name "${CONTAINER_NAME}" \
  --restart=always \
  "${IMAGE_NAME}"
