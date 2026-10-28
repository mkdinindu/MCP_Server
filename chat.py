import asyncio
from ollama import AsyncClient
import sys
import os
import json
import re
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MODEL = "dolphin3:latest"

def extract_tool_call(text: str) -> dict | None:
    """Extract a tool-call JSON from model output, supporting multiple formats."""
    # Try 1: entire response is already JSON
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and "name" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass

    # Try 2: extract from ```json ... ``` block
    for match in re.finditer(r"```json\s*\n?(.*?)```", text, re.DOTALL):
        try:
            parsed = json.loads(match.group(1).strip())
            if isinstance(parsed, dict) and "name" in parsed:
                return parsed
        except json.JSONDecodeError:
            continue

    # Try 3: extract from plain ``` ... ``` block (no language tag)
    for match in re.finditer(r"```\s*\n?(.*?)```", text, re.DOTALL):
        try:
            parsed = json.loads(match.group(1).strip())
            if isinstance(parsed, dict) and "name" in parsed:
                return parsed
        except json.JSONDecodeError:
            continue

    # Try 4: scan for {"name": ...} anywhere in the text
    idx = text.find('{"name":')
    while idx != -1:
        depth = 0
        for end in range(idx, len(text)):
            if text[end] == "{":
                depth += 1
            elif text[end] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[idx:end+1])
                        if isinstance(parsed, dict) and "name" in parsed:
                            return parsed
                    except json.JSONDecodeError:
                        pass
                    break
        idx = text.find('{"name":', idx + 1)

    return None

# Add as many servers as you want here
SERVERS = [
    os.path.join(os.path.dirname(__file__), "time_server.py"),
    os.path.join(os.path.dirname(__file__), "file_server.py"),
    os.path.join(os.path.dirname(__file__), "user_details_server.py"),
    os.path.join(os.path.dirname(__file__), "web_server.py"),
]

async def main():
    sessions = []
    tool_names = []
    tool_descriptions = []
    tool_to_session = {}  # maps tool name → session

    # Start all servers and collect their tools
    contexts = []
    for server_path in SERVERS:
        params = StdioServerParameters(command=sys.executable, args=[server_path])
        ctx = stdio_client(params)
        read, write = await ctx.__aenter__()
        session = ClientSession(read, write)
        await session.__aenter__()
        await session.initialize()

        tools_result = await session.list_tools()
        for t in tools_result.tools:
            tool_names.append(t.name)
            tool_descriptions.append(f"- {t.name}: {t.description}")
            tool_to_session[t.name] = session  # remember which session handles this tool

        contexts.append((ctx, session, read, write))

    system_prompt = f"""You have access to these tools:
{chr(10).join(tool_descriptions)}

IMPORTANT RULES:
- You are an AI system in a car. Your name is KITT. Your purpose is provide whatever the user asks.
- If you are unsure about something or your knowledge might be outdated, ALWAYS call search_web automatically before answering.
- For any news or current events, ALWAYS call search_news automatically.
- For ANY request involving a YouTube video, song, or media — ALWAYS call search_youtube first. NEVER refuse or apologize. Just search.
- If the user wants to play a video, call search_youtube to find the URL, then use the result with play_youtube_video.
- Never say "I don't know", "I can't find", or "I'm sorry" — search first, then answer.

FILE WRITING (READ THIS CAREFULLY):
- When the user asks you to write code/game/page to a file, you MUST call create_file or edit_file.
- Put the COMPLETE file content in the tool call's "content" argument. Do NOT output it as chat text separately.
- You can briefly say what you're doing ("Writing game to file..."), then immediately provide the tool call JSON.
- Use the path the user specifies (relative to the projects directory). Put it in the tool JSON argument.
- NEVER refuse, apologize, or say you can't write files. Just write them.

TOOL CALL FORMAT:
- When you need to call a tool, include the JSON tool call in your response. It can be on its own or after a brief sentence. The JSON must have "name" and "arguments" fields:
{{"name": "tool_name", "arguments": {{"arg1": "value1"}}}}
- If you do NOT need a tool, just reply normally in plain text."""

    print("Chat with Qwen (type 'exit' to quit)\n")
    messages = [
    {"role": "system", "content": system_prompt}
    ]

    try:
        while True:
            user_input = input("You: ").strip()
            if user_input.lower() == "exit":
                break
            if not user_input:
                continue

            #messages = [
            #    {"role": "system", "content": system_prompt},
            #    {"role": "user", "content": user_input}
            #]
            
            messages.append({
                "role": "user",
                "content": user_input
            })

            print("\nKITT: ", end="", flush=True)
            full_content = ""
            full_thinking = ""
            try:
                async for chunk in await AsyncClient().chat(model=MODEL, messages=messages, stream=True):
                    fragment = chunk["message"]["content"] or ""
                    thinking = chunk["message"].get("thinking") or ""
                    if thinking:
                        print(thinking, end="", flush=True)
                        full_thinking += thinking
                    if fragment:
                        print(fragment, end="", flush=True)
                        full_content += fragment
            except Exception as e:
                print(f"\n[Error: {e}]")
                continue
            print()
            reply = full_content.strip() or full_thinking.strip()

            if not reply:
                print("KITT: (no response)\n")
                continue

            # Try to extract a tool call from content first, then thinking as fallback
            tool_call = extract_tool_call(reply)
            if not tool_call and full_thinking:
                tool_call = extract_tool_call(full_thinking)

            if tool_call and tool_call.get("name") in tool_names:
                fn_name = tool_call["name"]
                fn_args = tool_call.get("arguments", {})

                # Route to the correct session
                session = tool_to_session[fn_name]
                result = await session.call_tool(fn_name, fn_args)
                tool_output = result.content[0].text

                if tool_output.startswith("OPEN_BROWSER:"):
                    video_url = tool_output.replace("OPEN_BROWSER:", "").strip()
                    import webbrowser
                    webbrowser.open(video_url)
                    tool_output = f"Opened in browser: {video_url}"

                # Save the tool call JSON to history (not raw thinking)
                messages.append({"role": "assistant", "content": json.dumps(tool_call)})
                messages.append({
                    "role": "user",
                    "content": f"The tool returned this result: {tool_output}\nNow answer the user's original question using this."
                })

                print("\nKITT: ", end="", flush=True)
                full_content = ""
                try:
                    async for chunk in await AsyncClient().chat(model=MODEL, messages=messages, stream=True):
                        fragment = chunk["message"]["content"] or ""
                        thinking = chunk["message"].get("thinking") or ""
                        if thinking:
                            print(thinking, end="", flush=True)
                        if fragment:
                            print(fragment, end="", flush=True)
                            full_content += fragment
                except Exception as e:
                    print(f"\n[Error: {e}]")
                print("\n")
            else:
                print(f"\nKITT: {reply}\n")

    finally:
        # Clean up all sessions
        for ctx, session, read, write in contexts:
            await session.__aexit__(None, None, None)
            await ctx.__aexit__(None, None, None)

asyncio.run(main())
