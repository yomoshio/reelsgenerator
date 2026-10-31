#!/usr/bin/env bash
# install-node <git url> <ref> — clone a ComfyUI custom node at a fixed ref and install its deps.
set -euo pipefail

url=$1
ref=$2
name=$(basename "$url" .git)
dest=/opt/comfy/custom_nodes/$name

git clone --filter=blob:none "$url" "$dest"
git -C "$dest" checkout --quiet "$ref"
if [[ -f $dest/requirements.txt ]]; then
    pip install -r "$dest/requirements.txt"
fi
rm -rf "$dest/.git"
