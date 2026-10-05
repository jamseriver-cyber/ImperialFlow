import argparse
import json
from pathlib import Path
import sys

from pydantic import ValidationError

from .runtime import Invocation, Runtime
from .runtime.errors import GovernanceError
from .runtime.models import TransitionRequest


def main():
    parser = argparse.ArgumentParser(description="ImperialFlow V1 local governance runtime")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("check", "submit"):
        p = sub.add_parser(command)
        p.add_argument("--request", required=True)
        p.add_argument("--context", required=True)
    p = sub.add_parser("begin")
    p.add_argument("--task", required=True)
    p.add_argument("--context", required=True)
    p.add_argument("--maintenance", action="store_true")
    p.add_argument("--reconciliation", action="store_true")
    sub.add_parser("render")
    sub.add_parser("recover")
    sub.add_parser("status")
    p = sub.add_parser("schema")
    p.add_argument("--output")
    args = parser.parse_args()
    try:
        runtime = Runtime(args.root)
        if args.command == "schema":
            result = TransitionRequest.model_json_schema()
            if args.output:
                Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
                result = {"result": "SCHEMA_EXPORTED", "path": args.output}
        elif args.command in {"check", "submit", "begin"}:
            context = Invocation.model_validate(json.loads(Path(args.context).read_text(encoding="utf-8-sig")))
            if args.command == "begin":
                result = runtime.begin(args.task, context, args.maintenance, args.reconciliation)
            else:
                data = json.loads(Path(args.request).read_text(encoding="utf-8-sig"))
                result = getattr(runtime, args.command)(data, context)
        elif args.command == "render":
            runtime.render()
            result = {"validator_result": "ALLOW", "result": "DERIVED_VIEW_GENERATED"}
        elif args.command == "recover":
            result = runtime.recover()["runtime"]
        else:
            registry = runtime.load()
            result = {"revision": registry["runtime"]["revision"], "tasks": registry["tasks"]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except GovernanceError as error:
        print(json.dumps({"validator_result": "DENY", "error_code": error.code, "detail": error.detail}, ensure_ascii=False))
        return 2
    except (ValidationError, ValueError, KeyError, OSError) as error:
        print(json.dumps({"validator_result": "DENY", "error_code": "SCHEMA_VALIDATION_FAILED", "detail": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
