from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import deps
from app.api.routes import router
from app.models import GateError
from app.review import ReviewError

app = FastAPI(title="Cultural Screenplay & Visual Adaptation Studio")
app.include_router(router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# Domain errors become clear, specific HTTP answers (never a 500 with a stack trace).
@app.exception_handler(ReviewError)
async def _review_error(_: Request, e: ReviewError):
    return JSONResponse({"detail": str(e)}, status_code=422)


@app.exception_handler(ValueError)
async def _value_error(_: Request, e: ValueError):
    return JSONResponse({"detail": str(e)}, status_code=422)


@app.exception_handler(GateError)
async def _gate_error(_: Request, e: GateError):
    return JSONResponse({"detail": str(e)}, status_code=409)


@app.exception_handler(deps.Busy)
async def _busy(_: Request, e: deps.Busy):
    return JSONResponse({"detail": str(e)}, status_code=409)


@app.exception_handler(KeyError)
async def _not_found(_: Request, e: KeyError):
    return JSONResponse({"detail": str(e.args[0]) if e.args else "not found"}, status_code=404)
