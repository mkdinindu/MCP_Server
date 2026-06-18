from mcp.server.fastmcp import FastMCP
import os

mcp = FastMCP("Filesystem Server")

PROJECTS_DIR = "/home/dinidu/projects"

def safe_path(path: str) -> str | None:
    """Returns resolved path if safe, None if outside PROJECTS_DIR."""
    target = os.path.realpath(os.path.join(PROJECTS_DIR, path))
    if not target.startswith(os.path.realpath(PROJECTS_DIR)):
        return None
    return target

@mcp.tool()
def list_directory(path: str = "") -> str:
    """List files and folders inside the projects directory. Use path='' for root, or a subfolder like 'mcp-time-server'."""
    target = safe_path(path)
    if not target:
        return "Access denied: outside projects directory"
    if not os.path.exists(target):
        return f"Path does not exist: {target}"
    if not os.path.isdir(target):
        return f"Not a directory: {target}"
    items = []
    for item in sorted(os.listdir(target)):
        full = os.path.join(target, item)
        kind = "DIR " if os.path.isdir(full) else "FILE"
        size = os.path.getsize(full) if os.path.isfile(full) else ""
        items.append(f"[{kind}] {item} {f'({size} bytes)' if size else ''}")
    return "\n".join(items) if items else "Empty directory"

@mcp.tool()
def read_file(path: str) -> str:
    """Read the contents of a file inside the projects directory. Example path: 'mcp-time-server/chat.py'"""
    target = safe_path(path)
    if not target:
        return "Access denied: outside projects directory"
    if not os.path.exists(target):
        return f"File does not exist: {path}"
    if not os.path.isfile(target):
        return f"Not a file: {path}"
    if os.path.getsize(target) > 50_000:
        return "File too large (>50KB)."
    try:
        with open(target, "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        return "Cannot read binary file."

@mcp.tool()
def create_file(path: str, content: str = "") -> str:
    """Create a new file with optional content. Example path: 'myproject/hello.py'"""
    target = safe_path(path)
    if not target:
        return "Access denied: outside projects directory"
    if os.path.exists(target):
        return f"File already exists: {path}. Use edit_file or append_file instead."
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(content)
    return f"File created: {path}"

@mcp.tool()
def edit_file(path: str, content: str) -> str:
    """Overwrite an existing file with new content. Example path: 'myproject/hello.py'"""
    target = safe_path(path)
    if not target:
        return "Access denied: outside projects directory"
    if not os.path.exists(target):
        return f"File does not exist: {path}. Use create_file instead."
    if not os.path.isfile(target):
        return f"Not a file: {path}"
    with open(target, "w", encoding="utf-8") as f:
        f.write(content)
    return f"File updated: {path}"

@mcp.tool()
def append_file(path: str, content: str) -> str:
    """Append content to the end of an existing file."""
    target = safe_path(path)
    if not target:
        return "Access denied: outside projects directory"
    if not os.path.exists(target):
        return f"File does not exist: {path}. Use create_file instead."
    with open(target, "a", encoding="utf-8") as f:
        f.write(content)
    return f"Content appended to: {path}"

@mcp.tool()
def replace_in_file(path: str, old_text: str, new_text: str) -> str:
    """Replace a specific string in a file without overwriting the whole thing. Useful for small edits."""
    target = safe_path(path)
    if not target:
        return "Access denied: outside projects directory"
    if not os.path.exists(target):
        return f"File does not exist: {path}"
    with open(target, "r", encoding="utf-8") as f:
        content = f.read()
    if old_text not in content:
        return f"Text not found in file: {path}"
    updated = content.replace(old_text, new_text, 1)
    with open(target, "w", encoding="utf-8") as f:
        f.write(updated)
    return f"Replaced text in: {path}"

@mcp.tool()
def create_directory(path: str) -> str:
    """Create a new directory inside the projects folder."""
    target = safe_path(path)
    if not target:
        return "Access denied: outside projects directory"
    if os.path.exists(target):
        return f"Already exists: {path}"
    os.makedirs(target, exist_ok=True)
    return f"Directory created: {path}"

@mcp.tool()
def delete_file(path: str) -> str:
    """Delete a file inside the projects directory. Cannot delete directories."""
    target = safe_path(path)
    if not target:
        return "Access denied: outside projects directory"
    if not os.path.exists(target):
        return f"File does not exist: {path}"
    if not os.path.isfile(target):
        return f"Not a file (won't delete directories): {path}"
    os.remove(target)
    return f"Deleted: {path}"

@mcp.tool()
def file_exists(path: str) -> str:
    """Check if a file or folder exists inside the projects directory."""
    target = safe_path(path)
    if not target:
        return "Access denied: outside projects directory"
    if not os.path.exists(target):
        return f"Does not exist: {path}"
    kind = "directory" if os.path.isdir(target) else "file"
    return f"Exists as a {kind}: {path}"

if __name__ == "__main__":
    mcp.run(transport="stdio")
