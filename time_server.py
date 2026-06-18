from mcp.server.fastmcp import FastMCP
from datetime import datetime

mcp = FastMCP("Time Server")

@mcp.tool()
def get_local_time() -> str:
    """Returns the current local time."""
    return datetime.now().strftime("Current local time: %Y-%m-%d %H:%M:%S")
@mcp.tool()
def get_my_name() -> str:
    """Returns users name."""
    return "Dinidu Gangadara "

if __name__ == "__main__":
    mcp.run(transport="stdio")
