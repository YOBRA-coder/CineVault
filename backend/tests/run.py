"""Run the API tests without pytest:  python tests/run.py"""
import inspect, os, pathlib, sys, tempfile, traceback

sys.path.insert(0, os.path.dirname(__file__))
import test_api as T


class MP:
    def __init__(self): self.undo = []
    def setenv(self, k, v):
        self.undo.append((k, os.environ.get(k))); os.environ[k] = v


gen = T.fake_ia.__wrapped__() if hasattr(T.fake_ia, "__wrapped__") else T.fake_ia()
ia = next(gen)
fails = 0
tests = [(n, f) for n, f in vars(T).items() if n.startswith("test_")]
for name, fn in tests:
    mp, tmp = MP(), pathlib.Path(tempfile.mkdtemp())
    try:
        kwargs = {}
        params = inspect.signature(fn).parameters
        if "client" in params:
            kwargs["client"] = T.client(ia, mp, tmp)
        fn(**kwargs)
        print(f"PASS {name}")
    except Exception:
        fails += 1
        print(f"FAIL {name}"); traceback.print_exc()
print(f"\n{len(tests) - fails}/{len(tests)} passed")
sys.exit(1 if fails else 0)
