# Backend（FastAPI）

> 说明：该后端用于“能力验证”，默认提供离线 demo（scripted LLM stream），不依赖外网。

## 运行

从仓库根目录开始（确保能 import `agently_skills_runtime`）：

```bash
python -m pip install -e .
python -m pip install -e projects/agently-skills-web-prototype/backend
uvicorn agently_skills_web_backend.app:app --reload --port 8000
```

## 测试

```bash
cd projects/agently-skills-web-prototype/backend
pytest -q
```
