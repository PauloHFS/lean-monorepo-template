"""Procrastinate App — entrypoint do sistema de filas.

Singleton do `procrastinate.App`. As tasks são declaradas nos módulos de
`app.jobs.tasks.*` e registradas via `@app.task(...)`.

Notas:
- O worker do Procrastinate **exige um connector async** (`PsycopgConnector`);
  connectors sync (psycopg2/SQLAlchemy) servem só para deferir em contexto sync.
  Por isso usamos `PsycopgConnector` com a DSN libpq (`database_url_procrastinate`).
- As tasks são carregadas no worker via `import_paths` (evita import circular
  entre `app.py` e os módulos de task). Quem for deferir importa a task
  diretamente, o que também registra o decorador.
"""
from __future__ import annotations

import os
import socket

import procrastinate

from app.core.config import settings

app = procrastinate.App(
    connector=procrastinate.PsycopgConnector(
        conninfo=settings.database_url_procrastinate,
    ),
    import_paths=["app.jobs.tasks.email"],
    worker_defaults={
        "concurrency": 4,
        "name": f"procrastinate-worker-{socket.gethostname()}-{os.getpid()}",
    },
)


def get_app() -> procrastinate.App:
    return app
