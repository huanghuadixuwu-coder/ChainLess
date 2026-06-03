import sys, traceback, json

def main():
    try:
        code = compile(open("/workspace/script.py").read(), "/workspace/script.py", "exec")
        exec(code, {"__builtins__": __builtins__})
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
