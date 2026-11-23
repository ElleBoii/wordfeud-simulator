"""Starta servern: python -m server [--port 8000]"""
import argparse
import socket
import sys

import uvicorn

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def lan_ip() -> str:
    """Datorns adress på det lokala nätet (inga paket skickas)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()

    from server.app import create_app
    app = create_app()
    s = app.state.settings.load()
    n = app.state.sims.n_workers(s)
    app.state.sims.warm(s)      # startar simuleringsprocesserna och laddar ordlistan i dem
    print()
    print(f"  Simulering: {n} {'process' if n == 1 else 'processer'}")
    print(f"  På datorn:  http://localhost:{args.port}")
    print(f"  På mobilen: http://{lan_ip()}:{args.port}   (samma wifi)")
    print()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
