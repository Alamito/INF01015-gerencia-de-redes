"""MCP server that exposes the network tools to Claude Code (stdio transport).

Claude Code starts this process itself; nothing here may print to stdout.
"""

from mcp.server.fastmcp import FastMCP

import net_tools

mcp = FastMCP("netsentinel", log_level="WARNING")

for tool in net_tools.ALL_TOOLS:
    mcp.tool()(tool)

if __name__ == "__main__":
    mcp.run()
