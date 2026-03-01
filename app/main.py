from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException

from app.loader import EntrypointError, ManifestError, ModuleDirectoryNotFound
from app.models import ExecuteRequest, ExecuteResponse
from app.runtime import ModuleExecutionError, RuntimeService


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

app = FastAPI(title="Amaryllis Runtime", version="0.1.0")
runtime_service = RuntimeService()


@app.post("/execute", response_model=ExecuteResponse)
def execute(request: ExecuteRequest) -> ExecuteResponse:
    try:
        return runtime_service.execute(request)
    except ModuleDirectoryNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ManifestError, EntrypointError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ModuleExecutionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
