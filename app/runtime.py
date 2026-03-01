from __future__ import annotations

import logging
import time

from pydantic import ValidationError

from app.context import build_context
from app.loader import ModuleLoader, ModuleLoaderError
from app.models import ExecuteRequest, ExecuteResponse, ModuleExecutionResult


class ModuleExecutionError(Exception):
    pass


class RuntimeService:
    def __init__(self, loader: ModuleLoader | None = None) -> None:
        self.loader = loader or ModuleLoader()
        self.logger = logging.getLogger("amaryllis.runtime")

    def execute(self, request: ExecuteRequest) -> ExecuteResponse:
        context = build_context(user_id=request.user_id, input_data=request.input)
        request_id = context["request_id"]
        started_at = time.perf_counter()

        self.logger.info(
            "execution_started request_id=%s module=%s",
            request_id,
            request.module,
        )

        try:
            loaded_module = self.loader.load(request.module)
            raw_result = loaded_module.run(context)
            result = ModuleExecutionResult.model_validate(raw_result)
        except ModuleLoaderError:
            execution_time_ms = self._elapsed_ms(started_at)
            self.logger.exception(
                "execution_failed request_id=%s module=%s execution_time_ms=%d",
                request_id,
                request.module,
                execution_time_ms,
            )
            raise
        except ValidationError as exc:
            execution_time_ms = self._elapsed_ms(started_at)
            self.logger.exception(
                "execution_failed request_id=%s module=%s execution_time_ms=%d",
                request_id,
                request.module,
                execution_time_ms,
            )
            raise ModuleExecutionError(f"Module returned invalid result: {exc}") from exc
        except Exception as exc:
            execution_time_ms = self._elapsed_ms(started_at)
            self.logger.exception(
                "execution_failed request_id=%s module=%s execution_time_ms=%d",
                request_id,
                request.module,
                execution_time_ms,
            )
            raise ModuleExecutionError(f"Module execution failed: {exc}") from exc

        execution_time_ms = self._elapsed_ms(started_at)
        self.logger.info(
            "execution_finished request_id=%s module=%s execution_time_ms=%d",
            request_id,
            request.module,
            execution_time_ms,
        )

        return ExecuteResponse(
            request_id=request_id,
            module=request.module,
            output=result.output,
            memory_write=result.memory_write,
            execution_time_ms=execution_time_ms,
        )

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return int((time.perf_counter() - started_at) * 1000)
