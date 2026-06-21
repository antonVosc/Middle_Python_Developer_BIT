import logging
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api.routes import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="DocFlow - Обработка реестров платежей",
    description=(
        "Принимает реестры платежей в формате Excel, извлекает структурированные данные с помощью LLM, "
        "хранит их в PostgreSQL и передает отчеты во внешний BIT API."
    ),
    version="1.0.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)

_frontend_dirs = ["/app/frontend", "frontend"]

for _d in _frontend_dirs:
    if os.path.isfile(os.path.join(_d, "index.html")):
        app.mount("/ui", StaticFiles(directory=_d, html=True), name="frontend")

        break