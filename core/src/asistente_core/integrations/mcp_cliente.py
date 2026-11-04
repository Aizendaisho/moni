"""Cliente MCP mínimo: Moni habla con servidores MCP locales (stdio).

Regla de seguridad: Moni nunca le pasa al modelo las herramientas de un servidor MCP tal cual.
Cada integración declara una lista cerrada de herramientas permitidas y las envuelve en
herramientas propias de Moni, con sus niveles de permiso. Así un servidor con cientos de
herramientas (algunas capaces de ejecutar código) solo expone lo que se revisó.
"""

import json
import logging
from dataclasses import dataclass

log = logging.getLogger("moni.mcp")


class NoPermitida(ValueError):
    pass


@dataclass
class ServidorMCP:
    nombre: str
    comando: str
    argumentos: list[str]
    permitidas: frozenset[str]
    entorno: dict[str, str] | None = None
    timeout: float = 180

    async def llamar_varias(self, llamadas: list[tuple[str, dict]]) -> list[dict]:
        """Abre una sesión, hace las llamadas en orden y la cierra. Devuelve por cada una
        {"ok", "datos" | "error"}. Rechaza cualquier herramienta fuera de la lista."""
        for nombre, _ in llamadas:
            if nombre not in self.permitidas:
                raise NoPermitida(f"{self.nombre}: la herramienta {nombre} no está permitida")
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(command=self.comando, args=self.argumentos, env=self.entorno)
        resultados: list[dict] = []
        async with (
            stdio_client(params) as (lector, escritor),
            ClientSession(lector, escritor) as sesion,
        ):
            await sesion.initialize()
            for nombre, args in llamadas:
                try:
                    r = await sesion.call_tool(nombre, args)
                    resultados.append(_normalizar(r))
                except Exception as exc:  # noqa: BLE001
                    log.warning("%s.%s falló: %s", self.nombre, nombre, exc)
                    resultados.append({"ok": False, "error": str(exc)})
        return resultados


def _normalizar(r) -> dict:
    """Resultado de call_tool -> {"ok", "datos"|"error"} (compatible con mcp 1.x y 2.x)."""
    error = getattr(r, "is_error", None)
    if error is None:
        error = getattr(r, "isError", False)
    estructurado = getattr(r, "structured_content", None)
    if estructurado is None:
        estructurado = getattr(r, "structuredContent", None)
    texto = " ".join(getattr(c, "text", "") or "" for c in getattr(r, "content", []) or [])
    if error:
        return {"ok": False, "error": texto[:500] or "error sin detalle"}
    if estructurado is None and texto:
        try:
            estructurado = json.loads(texto)
        except ValueError:
            estructurado = {"texto": texto}
    return {"ok": True, "datos": estructurado or {}}
