"""Run a local desktop backend with explicit external or owned PostgreSQL."""
import argparse
import os
from contextlib import nullcontext
from pathlib import Path
import sys
import socket

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.runtime_paths import RuntimePaths
from desktop.server import attach_frontend, configure_environment, validate_boot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    from backend.resources import resource_root
    parser.add_argument("--resources", type=Path, default=resource_root())
    parser.add_argument("--local-app-data", type=Path, default=Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else None)
    parser.add_argument("--port", type=int, default=18750)
    parser.add_argument("--check", action="store_true", help="read-only preflight, no directories, database or server")
    parser.add_argument("--managed-postgres", action="store_true", help="initialize/reuse only this application's owned cluster")
    parser.add_argument("--pg-bin", type=Path, help="reviewed PostgreSQL 18 bin directory; defaults to resources/postgres/bin")
    parser.add_argument("--pg-port", type=int, default=18760)
    args = parser.parse_args()
    try:
        if args.local_app_data is None:
            raise ValueError("desktop_local_app_data_required")
        paths = RuntimePaths.windows(resources=args.resources, local_app_data=args.local_app_data)
        manager = None
        if args.managed_postgres:
            if os.environ.get("DESKTOP_DATABASE_URL"):
                raise ValueError("desktop_external_and_managed_database_conflict")
            if args.pg_port == args.port:
                raise ValueError("desktop_database_and_http_port_conflict")
            from desktop.postgres import ManagedPostgres
            manager = ManagedPostgres(paths, args.pg_bin or paths.resources / "postgres/bin", port=args.pg_port)
            manager.preflight()
            for resource in ("alembic.ini", "migrations/env.py", "seed/syllabus.json", "seed/questions.json"):
                if not (paths.resources / resource).is_file():
                    raise ValueError("desktop_bootstrap_resources_missing")
            # Read-only preflight must not create credentials or initialize PG.
            database_url = f"postgresql+psycopg://preflight@127.0.0.1:{args.pg_port}/kaoyan_desktop"
        else:
            database_url = os.environ.get("DESKTOP_DATABASE_URL", "")
        if not database_url:
            raise ValueError("desktop_database_url_required")
        validate_boot(paths, database_url, args.port)
        if args.check:
            print("desktop_preflight_ok; no changes made; owned initialization is opt-in")
            return
        # Reserve HTTP before initializing/migrating any database.
        with socket.socket() as listener:
            if os.name == "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                listener.bind(("127.0.0.1", args.port))
                listener.listen(128)
            except OSError:
                raise ValueError("desktop_http_port_in_use") from None
            with manager if manager is not None else nullcontext():
                if manager is not None:
                    database_url = manager.database_url
                frontend = configure_environment(paths, database_url, args.port)
                paths.ensure_data_dirs()
                if manager is not None:
                    from desktop.bootstrap import prepare_schema
                    prepare_schema(manager)
                from backend.app import create_app
                import uvicorn
                app = attach_frontend(create_app(), frontend, port=args.port)
                uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=args.port, proxy_headers=False, access_log=False)).run(sockets=[listener])
    except ValueError as error:
        # Only our allowlisted categories; never echo a DSN/secret-bearing exception.
        category = str(error)
        parser.exit(2, (category if category.startswith("desktop_") and " " not in category else "desktop_configuration_invalid") + "\n")


if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    main()
