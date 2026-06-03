# Runtime Bridge Capability Showcase

Live-server showcase for the upgraded capability-runtime bridge. The checked-in
`index.html` is only a static shell with placeholders; real model output is
returned by `server.py` at runtime.

Serve it locally:

```bash
python examples/10_runtime_bridge_showcase/server.py --host 127.0.0.1 --port 8090
```

Then open:

```text
http://127.0.0.1:8090/
```

The served page calls the real provider from the server process and displays
sanitized model output plus NodeReport usage evidence. It does not contain API
keys or raw provider payloads.
