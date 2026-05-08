"""Entry point for ``python -m q2google``.

Delegates to the Typer application defined in :mod:`q2google.cli`.
"""

from q2google.cli import app

if __name__ == "__main__":
    app()
