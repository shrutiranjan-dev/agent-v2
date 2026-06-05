from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("agent-platform-fake-mcp")


@mcp.tool()
def echo(text: str) -> dict[str, str]:
    """Echo text back to the caller."""
    return {"echo": text}


if __name__ == "__main__":
    mcp.run("stdio")
