"""Tasks de jobs (Procrastinate).

Cada módulo declara tasks via `@app.task(...)` (de `app.jobs.app`). Importar o
módulo é o que registra a task no App. O worker carrega esses módulos via
`import_paths` configurado em `app.jobs.app`.
"""
from app.jobs.tasks.email import send_email

__all__ = ["send_email"]
