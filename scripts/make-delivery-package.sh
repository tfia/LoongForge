#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
task_root="${ROOT:-$(cd -- "${script_dir}/.." && pwd)}"
task_name="${PACKAGE_NAME:-loongforge-delivery}"
task_stamp="${PACKAGE_STAMP:-$(date +%Y%m%d-%H%M%S)}"
task_out_dir="${PACKAGE_OUT_DIR:-${task_root}/dist}"
task_prefix="${task_name}-${task_stamp}"
task_tar="${task_out_dir}/${task_prefix}.tar.gz"

cd "${task_root}"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "error: worktree is not clean; commit or stash changes before packaging" >&2
  git status --short >&2
  exit 1
fi

mkdir -p "${task_out_dir}"
git archive --format=tar --prefix="${task_prefix}/" HEAD | gzip -9 > "${task_tar}"

task_sha="$(shasum -a 256 "${task_tar}" | awk '{print $1}')"
cat > "${task_tar}.sha256" <<EOF
${task_sha}  $(basename -- "${task_tar}")
EOF

printf 'package: %s\n' "${task_tar}"
printf 'sha256:  %s\n' "${task_sha}"
printf 'verify:  shasum -a 256 -c %q\n' "${task_tar}.sha256"
