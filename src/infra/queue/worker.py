"""
Entry point for the Arq worker.
Run via: arq src.infra.queue.worker.WorkerSettings
"""
from src.infra.queue.settings import WorkerSettings

__all__ = ["WorkerSettings"]
