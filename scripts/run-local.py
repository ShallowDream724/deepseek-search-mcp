"""Launch stdio with a Windows user-level key when the parent has stale environment."""

import os


def main() -> int:
    if os.name == "nt" and not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as environment:
                value, _ = winreg.QueryValueEx(environment, "DEEPSEEK_API_KEY")
            if isinstance(value, str) and value.strip():
                os.environ["DEEPSEEK_API_KEY"] = value.strip()
        except FileNotFoundError:
            pass

    from deepseek_search_mcp.cli import main as run_server

    return run_server()


if __name__ == "__main__":
    raise SystemExit(main())
