"""Módulo `studio` FALSO para pruebas locales (la plataforma aporta el real). No se sube."""


def tool(fn=None, **kw):
    if fn is None:
        return lambda f: f
    return fn


def artifacts(*paths, message=""):
    return {"artifacts": list(paths), "message": message}
