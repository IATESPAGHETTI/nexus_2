#!/bin/sh
# Builds a clean folder that can be pushed to a Hugging Face Space:
#   sh deploy/space/make_bundle.sh /tmp/nexus-space
#   cd /tmp/nexus-space && git init && git add -A && git commit -m nexus && \
#     git remote add space https://huggingface.co/spaces/<user>/<space> && git push space HEAD:main
# Only files tracked by git are copied (so no .env, no venvs, no results), and the Space's Dockerfile + README are put in place.
set -e
OUT="${1:?usage: make_bundle.sh <output-dir>}"
rm -rf "$OUT" && mkdir -p "$OUT"
git ls-files -z | xargs -0 -I{} cp --parents {} "$OUT"
cp Dockerfile.space "$OUT/Dockerfile"
cp deploy/space/README.space.md "$OUT/README.md"
# drop what the Space does not need (keeps the upload small)
rm -rf "$OUT/docs" "$OUT/evaluation/results" "$OUT/.github" "$OUT/.claude"
echo "bundle ready in $OUT"
