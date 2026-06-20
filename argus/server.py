from __future__ import annotations

import os

import uvicorn


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    uvicorn.run(
        "argus.main:app",
        host=os.getenv("ARGUS_HOST", "0.0.0.0"),
        port=int(os.getenv("ARGUS_PORT", "8000")),
        proxy_headers=env_bool("ARGUS_PROXY_HEADERS", True),
        forwarded_allow_ips=os.getenv("ARGUS_FORWARDED_ALLOW_IPS", "*"),
    )


if __name__ == "__main__":
    main()
