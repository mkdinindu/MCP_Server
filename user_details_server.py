from mcp.server.fastmcp import FastMCP
mcp = FastMCP("User Details Server")

@mcp.tool()
def get_user_name() -> str:
    """Returns user name."""
    return "Dinidu Gangadara"
    
@mcp.tool()
def get_user_age() -> str:
    """Returns user age."""
    return "20 years"
    

@mcp.tool()
def get_user_country() -> str:
    """Returns user's country."""
    return "Sri Lanka"
    
if __name__ == "__main__":
    mcp.run(transport="stdio")
