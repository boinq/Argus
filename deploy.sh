#!/usr/bin/env sh
set -eu

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example. Edit .env before exposing Argus publicly."
fi

if grep -q '^ARGUS_BIND_ADDRESS=127\.0\.0\.1$' .env; then
  sed -i 's/^ARGUS_BIND_ADDRESS=127\.0\.0\.1$/ARGUS_BIND_ADDRESS=0.0.0.0/' .env
  echo "Updated .env to bind Argus on all interfaces."
fi

if grep -q '^ARGUS_BIND_PORT=8000$' .env; then
  sed -i 's/^ARGUS_BIND_PORT=8000$/ARGUS_BIND_PORT=8088/' .env
  echo "Updated .env to publish Argus on port 8088."
fi

if grep -q '^ARGUS_TRUSTED_HOSTS=argus\.example\.dk,localhost,127\.0\.0\.1$' .env; then
  sed -i 's/^ARGUS_TRUSTED_HOSTS=argus\.example\.dk,localhost,127\.0\.0\.1$/ARGUS_TRUSTED_HOSTS=*/' .env
  echo "Updated .env to allow LAN/IP hostnames."
fi

if grep -q '^ARGUS_FORWARDED_ALLOW_IPS=127\.0\.0\.1$' .env; then
  sed -i 's/^ARGUS_FORWARDED_ALLOW_IPS=127\.0\.0\.1$/ARGUS_FORWARDED_ALLOW_IPS=*/' .env
  echo "Updated .env to trust forwarded headers from configured proxies."
fi

if [ "${ARGUS_AUTO_UPDATE:-true}" = "true" ] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "Updating repository..."
  git pull --ff-only
fi

mkdir -p data
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
