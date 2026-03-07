"""
pytest configuration: mark async tests with asyncio.
"""
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "asyncio: mark test as asyncio coroutine",
    )
