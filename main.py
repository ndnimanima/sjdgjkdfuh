"""Compatibility entry point.

Some Python hosts expect ``main:app`` while others accept an ASGI path such as
``app.main:app``. Both work: this module simply re-exports the real application.
"""

from app.main import app  # noqa: F401

if __name__ == "__main__":
    import os

    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
