import argparse

from ui.tk_app import run_app

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--web", action="store_true")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    if args.web:
        from ui.web_app import create_app

        app = create_app()
        app.run(host=args.host, port=args.port, debug=False, threaded=True)
    else:
        run_app()
