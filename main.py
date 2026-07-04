"""APEX-7 entrypoint — runs the FastAPI backend (api/main.py) via uvicorn.

For local development with hot reload, prefer:
    uvicorn api.main:app --reload --port 8000
"""

import logging

import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s/%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
