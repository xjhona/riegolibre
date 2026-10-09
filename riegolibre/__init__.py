"""RiegoLibre: diseño de riego tecnificado para QGIS."""


def classFactory(iface):  # noqa: N802 (nombre exigido por QGIS)
    from .plugin import RiegoLibrePlugin
    return RiegoLibrePlugin(iface)
