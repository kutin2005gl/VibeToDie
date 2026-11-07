"""Regenerate the Python (ai/app/pb) and Go (order-service/internal/pb) code from the repo-root proto/ folder:
`cd ai && .venv/Scripts/python scripts/gen_proto.py`. The Go step needs protoc-gen-go and protoc-gen-go-grpc on PATH."""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

AI = Path(__file__).resolve().parent.parent
PROTO = AI.parent / "proto"
OUT = AI / "app" / "pb"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    files = [p.relative_to(PROTO).as_posix() for p in PROTO.rglob("*.proto")]
    subprocess.run(
        [sys.executable, "-m", "grpc_tools.protoc", f"-I{PROTO}", f"--python_out={OUT}",
         f"--grpc_python_out={OUT}", f"--pyi_out={OUT}", *files],
        check=True,
    )
    # protoc emits `from orders.v1 import x_pb2`; make it resolve inside the app package.
    for py in [p for p in OUT.rglob("*_pb2*") if p.suffix in (".py", ".pyi")]:
        text = py.read_text(encoding="utf-8")
        fixed = re.sub(r"^from (\w+(?:\.\w+)*) import (\w+_pb2)", r"from app.pb.\1 import \2", text, flags=re.M)
        py.write_text(fixed, encoding="utf-8")
    for d in [OUT, *[p for p in OUT.rglob("*") if p.is_dir() and p.name != "__pycache__"]]:
        (d / "__init__.py").touch()


def gen_go() -> None:
    if not (shutil.which("protoc-gen-go") and shutil.which("protoc-gen-go-grpc")):
        print("skip Go: protoc-gen-go / protoc-gen-go-grpc not on PATH")
        return
    orders = AI.parent / "order-service"
    pkg = "nexus/order-service/internal/pb/ordersv1"
    opts = [f"module=nexus/order-service", f"Morders/v1/orders.proto={pkg}"]
    cmd = [sys.executable, "-m", "grpc_tools.protoc", f"-I{PROTO}", f"--go_out={orders}", f"--go-grpc_out={orders}"]
    for o in opts:
        cmd += [f"--go_opt={o}", f"--go-grpc_opt={o}"]
    subprocess.run([*cmd, "orders/v1/orders.proto"], check=True, env=os.environ)


if __name__ == "__main__":
    main()
    gen_go()
