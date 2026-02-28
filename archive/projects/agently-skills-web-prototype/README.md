# 全量能力验证 Web 原型（Agently × Skills Runtime SDK）

> 目的：用一个小型 Web 应用把“全量能力覆盖”落成可运行、可复刻、可回归的验证入口。  
> 注意：这是参考应用/原型，不是生产交付物。

---

## 1) 结构

- `backend/`：FastAPI 后端（SSE + approvals + run lifecycle）
- `frontend/`：React + Vite 前端（展示事件流、发起 run、提交审批）

## 2) 依赖与冻结（Freeze）

冻结定义（与你的口径一致）：

- `agently`：来自 PyPI（版本号冻结）
- `skills-runtime-sdk-python`：来自 PyPI（版本号冻结）
- 本仓 `capability-runtime`：停止开发即冻结（本原型默认通过“本地路径/同仓安装”方式引用）

冻结清单（Source of Truth）：
- `freeze-manifest.yml`

## 3) 后端运行（本地开发）

在仓库根目录创建虚拟环境并安装依赖（示例，二选一即可）：

```bash
# 方式 A：在仓库根目录安装本包（让原型能 import capability_runtime）
python -m pip install -e .

# 方式 B：只为原型单独装后端依赖（仍需要能 import capability_runtime）
python -m pip install -e projects/agently-skills-web-prototype/backend
```

启动后端：

```bash
uvicorn agently_skills_web_backend.app:app --reload --port 8000
```

说明：
- 默认模式为 `demo`（离线 scripted backend），不依赖 agently/外网 API key。
- 若你安装了 `agently` 且配置了真实 requester，可在后端配置中切换到 `real` 模式做冒烟验证（见 `backend/.env.example`）。

## 4) 前端运行（本地开发）

```bash
cd projects/agently-skills-web-prototype/frontend
npm install
npm run dev
```

然后访问 Vite 输出的本地地址（默认 `http://localhost:5173`）。

## 5) 离线回归（后端）

```bash
cd projects/agently-skills-web-prototype/backend
pytest -q
```
