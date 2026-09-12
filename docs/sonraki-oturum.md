# Sonraki oturuma bırakılanlar

Bu oturumda **yapılmayacak** işler. Buraya taşınma sebepleriyle birlikte.

## Görev 8 — mcp 2.x (MCPServer API) geçişi

`pyproject.toml` şu an `mcp>=1.2.0,<2` ile pinli. Sebep: `uv` 2026-09-12'de
mcp 2.2.0 çekti ve sunucu hiç import edilemedi:

```
ModuleNotFoundError: No module named 'mcp.server.fastmcp'. This is mcp 2.x,
where FastMCP was renamed to MCPServer (from mcp.server.mcpserver import
MCPServer) and other APIs changed
```

Pin geçici bir çözüm; 1.x sonsuza kadar yaşamaz. Geçişte dokunulacaklar:

- `from mcp.server.fastmcp import FastMCP` → `from mcp.server.mcpserver import MCPServer`
- `mcp = FastMCP("upnote-lens")` → `MCPServer(...)`
- `@mcp.tool()` dekoratörleri ve `mcp.run()` çağrısı — 2.x imzaları
- Geçiş rehberi: https://py.sdk.modelcontextprotocol.io/v2/migration/

Yalnızca `server.py` (113 satır) etkileniyor; `db.py` ve `writer.py` MCP
paketine hiç dokunmuyor.

Geçişten sonra doğrulama: `uv run upnote-lens-mcp` ile stdio üzerinden
`initialize` → `tools/list` → `tools/call list_recent` el sıkışması. Bu
oturumda 1.30.0 ile çalıştığı bu yöntemle doğrulandı (10 araç listelendi).
