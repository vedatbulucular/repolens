"""Problem-detail exceptions and handlers for the HTTP API."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from repolens_api.schemas import ProblemDetail


def problem_response(description: str) -> dict[str, object]:
    """Describe one problem-detail response for generated OpenAPI documents."""
    return {
        "description": description,
        "content": {
            "application/problem+json": {
                "schema": ProblemDetail.model_json_schema(),
            }
        },
    }


class ApiProblem(Exception):
    """Exception carrying a safe machine-readable API problem."""

    def __init__(self, problem: ProblemDetail) -> None:
        self.problem = problem
        super().__init__(problem.title)


def problem(
    *,
    type_: str,
    title: str,
    status: int,
    detail: str,
) -> ApiProblem:
    """Build an API problem exception without internal implementation details."""
    return ApiProblem(ProblemDetail(type=type_, title=title, status=status, detail=detail))


def install_error_handlers(app: FastAPI) -> None:
    """Install consistent problem-detail handlers on the FastAPI application."""

    @app.exception_handler(ApiProblem)
    async def handle_api_problem(_request: Request, exc: ApiProblem) -> JSONResponse:
        return JSONResponse(
            status_code=exc.problem.status,
            content=exc.problem.model_dump(),
            media_type="application/problem+json",
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        _request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        request_problem = ProblemDetail(
            type="invalid_request",
            title="Invalid request",
            status=422,
            detail="The request body or path parameters are invalid.",
        )
        return JSONResponse(
            status_code=request_problem.status,
            content=request_problem.model_dump(),
            media_type="application/problem+json",
        )
