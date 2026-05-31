# Runtime Bridge Capability Showcase

Static showcase for the upgraded capability-runtime bridge.

Serve it locally:

```bash
python examples/10_runtime_bridge_showcase/server.py --host 100.66.215.80 --port 8090
```

Then open:

```text
http://100.66.215.80:8090/
```

The page calls the real provider from the server process and displays sanitized
model output plus NodeReport usage evidence. It does not contain API keys or raw
provider payloads.
