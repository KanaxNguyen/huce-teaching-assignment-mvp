#!/bin/sh
# Assemble the folder that is pushed to the Hugging Face Space repository.
# Usage: deploy/huggingface/prepare_space.sh <empty-target-dir>
set -e
target="${1:?usage: prepare_space.sh <empty-target-dir>}"
root="$(cd "$(dirname "$0")/../.." && pwd)"
if [ -e "$target" ] && [ -n "$(ls -A "$target" 2>/dev/null)" ]; then echo "target must be empty: $target" >&2; exit 1; fi
mkdir -p "$target/apps"
rsync -a --exclude tests --exclude __pycache__ --exclude '*.db' --exclude '*.egg-info' --exclude run_adversarial_audit.py "$root/apps/api" "$target/apps/"
cp "$root/alembic.ini" "$target/alembic.ini"
cp "$root/deploy/huggingface/Dockerfile" "$root/deploy/huggingface/entrypoint.sh" "$target/"
cp "$root/deploy/huggingface/README.space.md" "$target/README.md"
echo "Space folder ready at $target ($(du -sh "$target" | cut -f1))"
