"""Pytest fixtures compartilhadas."""
import os

# Aponta para um .env mínimo válido durante os testes unitários
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_DB", "app")
os.environ.setdefault("POSTGRES_USER", "app")
os.environ.setdefault("POSTGRES_PASSWORD", "app")
os.environ.setdefault("SECRET_KEY", "x" * 32)