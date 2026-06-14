import json
import os
import socket
import sys

CONTROL_SOCKET = "/run/chainless/subagent.sock"


def spawn_sub_agent(prompt, context=""):
    if not isinstance(prompt, str) or not isinstance(context, str):
        raise TypeError("prompt and context must be strings")
    request = {
        "capability": os.environ["CHAINLESS_SUBAGENT_CAPABILITY"],
        "method": "spawn_sub_agent",
        "params": {"prompt": prompt, "context": context},
    }
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(CONTROL_SOCKET)
        client.sendall(json.dumps(request).encode("utf-8") + b"\n")
        response = b""
        while not response.endswith(b"\n"):
            chunk = client.recv(65536)
            if not chunk:
                break
            response += chunk
    payload = json.loads(response.decode("utf-8"))
    if payload.get("ok") is not True:
        raise RuntimeError(payload.get("error", "sub-agent RPC rejected"))
    return payload["result"]

def main():
    try:
        code = compile(open("/workspace/script.py").read(), "/workspace/script.py", "exec")
        exec(code, {"__builtins__": __builtins__, "spawn_sub_agent": spawn_sub_agent})
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
