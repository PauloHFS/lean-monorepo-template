"""Tasks de jobs registradas por `kind`.

Padrão: cada task é uma `async def` que recebe um `JobContext`
(com sessão, payload, logger) e retorna nada (raise para falhar).
"""
from app.jobs.tasks.email import send_email
from app.jobs.tasks.registry import JobContext, TaskFn, register_task

# Registra todas as tasks aqui (importante: o registry é populado como efeito
# colateral do import deste módulo).
register_task("email.send", send_email)

__all__ = ["JobContext", "TaskFn", "register_task", "send_email"]
