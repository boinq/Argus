#!/usr/bin/env sh
set -eu

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example. Edit .env before exposing Argus publicly."
fi

mkdir -p data
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
