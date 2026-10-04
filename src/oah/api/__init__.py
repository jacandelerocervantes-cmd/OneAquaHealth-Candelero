"""FastAPI application layer.

Deliberately does NOT re-export `app` here: the FastAPI instance lives in the submodule
`oah.api.app`, and re-exporting a symbol named `app` from this package's `__init__.py` would
shadow the `oah.api.app` submodule itself (a well-known Python ambiguity when a package and
one of its submodules share a name with a re-exported attribute). Import it explicitly:

    from oah.api.app import app
"""
