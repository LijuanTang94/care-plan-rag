#!/usr/bin/env bash
# Build the deployment zips for the 3 Lambdas: shared business modules + handler + Linux-platform dependencies.
# The shared modules are the exact same files as the local FastAPI app — truly one codebase, two entry points.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SHARED="db.py models.py services.py schemas.py internal_order.py exceptions.py llm_service.py"
# Lambda runs on Linux x86_64, so we must install the matching platform wheels (pydantic_core/anthropic have compiled parts)
PLAT="--platform manylinux2014_x86_64 --implementation cp --python-version 3.12 --only-binary=:all:"

build() {
  local name=$1 handler=$2 deps=$3
  local d; d=$(mktemp -d)
  pip3 install -q $PLAT --target "$d" $deps
  (cd "$ROOT" && cp $SHARED "$d/")
  cp "$ROOT/aws/handlers/$handler" "$d/lambda_function.py"
  (cd "$d" && zip -qr "$ROOT/aws/$name.zip" . -x "*__pycache__*")
  rm -rf "$d"
  echo "$name.zip -> $(du -h "$ROOT/aws/$name.zip" | cut -f1)"
}

build get-order     get_order.py     "sqlalchemy pg8000 pydantic"
build create-order  create_order.py  "sqlalchemy pg8000 pydantic"
build generate-plan generate_plan.py "sqlalchemy pg8000 pydantic anthropic"
