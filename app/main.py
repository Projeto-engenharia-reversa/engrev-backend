from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import artifacts, auth, projects, runs
from app.core.config import settings
from app.core.exceptions import AppError

app = FastAPI(title="EngRev API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"code": exc.code, "message": exc.message})


app.include_router(auth.router, prefix="/api/auth")
app.include_router(projects.router, prefix="/api/projects")
app.include_router(runs.router, prefix="/api/runs")
app.include_router(artifacts.router, prefix="/api/artifacts")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
