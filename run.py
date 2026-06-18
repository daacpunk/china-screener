"""Local convenience launcher: `python run.py`.

Production/Railway uses the Procfile's uvicorn command (which is $PORT-aware).
"""
import os

import uvicorn

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=bool(os.environ.get("RELOAD")))
