import asyncio
import ollama
import sys
import os
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

MODEL = "gemma4:e2b"

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
- For any YouTube video requests, ALWAYS call search_youtube.
- VERY IMPORTANT If user says play a certain video, ALWAYS call search_youtube.
- Never say "I don't know" — search first, then answer.
- If you need to call a tool, respond with ONLY this JSON and nothing else:
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

            response = ollama.chat(model=MODEL, messages=messages)
            reply = response["message"]["content"].strip()
            
            

            if reply.startswith("```"):
                reply = reply.split("```")[1]
                if reply.startswith("json"):
                    reply = reply[4:]
                reply = reply.strip()

            try:
                parsed = json.loads(reply)
                if "name" in parsed and parsed["name"] in tool_names:
                    fn_name = parsed["name"]
                    fn_args = parsed.get("arguments", {})

                    # Route to the correct session
                    session = tool_to_session[fn_name]
                    result = await session.call_tool(fn_name, fn_args)
                    tool_output = result.content[0].text
                    
                    if tool_output.startswith("OPEN_BROWSER:"):
                        video_url = tool_output.replace("OPEN_BROWSER:", "").strip()
                        import webbrowser
                        webbrowser.open(video_url)
                        tool_output = f"Opened in browser: {video_url}"

                    messages.append({"role": "assistant", "content": reply})
                    messages.append({
                        "role": "user",
                        "content": f"The tool returned this result: {tool_output}\nNow answer the user's original question using this."
                    })

                    final = ollama.chat(model=MODEL, messages=messages)
                    print(f"\nQwen: {final['message']['content'].strip()}\n")
                else:
                    print(f"\nQwen: {reply}\n")
            except json.JSONDecodeError:
                print(f"\nQwen: {reply}\n")

    finally:
        # Clean up all sessions
        for ctx, session, read, write in contexts:
            await session.__aexit__(None, None, None)
            await ctx.__aexit__(None, None, None)

asyncio.run(main())
