# Test Cases: Integration Smoke（Agently requester + Skills sources redis/pgsql）

## Overview
- **Feature**：开发机可复刻的 `pytest -m integration` 冒烟集合（不依赖 CI，但必须给出一键复刻路径）
- **Requirements Source**：
  - `tests/test_integration_agently_requester_smoke.py`
  - `tests/test_integration_sources_redis_pgsql_smoke.py`
  - `docs/internal/specs/engineering-spec/05_Testing/TEST_PLAN.md`
- **Test Coverage**：覆盖 requester 构造最小契约、redis/pgsql sources scan 最小契约、缺环境时的明确 skip 口径
- **Last Updated**：2026-02-22

## Test Case Categories

### 1. Functional Tests

#### TC-F-001: Agently OpenAICompatible requester 构造与最小 request_data 形态
- **Requirement**：`tests/test_integration_agently_requester_smoke.py` 目标说明（不打外网）
- **Priority**：High
- **Preconditions**：
  - 已安装 `agently==4.0.7`，或存在本地 sibling `../Agently`
- **Test Steps**：
  1. 运行 `python -m pytest -m integration -q tests/test_integration_agently_requester_smoke.py`
  2. 观察 `generate_request_data()` 返回结构
- **Expected Results**：
  - `request_url` 非空
  - `headers` 为 dict
  - `data` 为 dict
- **Postconditions**：无

#### TC-F-002: Skills sources（redis/pgsql）scan 冒烟（可为空但不得抛错）
- **Requirement**：`tests/test_integration_sources_redis_pgsql_smoke.py` 目标说明
- **Priority**：High
- **Preconditions**：
  - 本机可用 docker
  - redis + postgres 已启动
  - pgsql 已执行 SDK migration（`agent.skills_catalog`）
  - 已设置环境变量：
    - `AGENTLY_SKILLS_RUNTIME_TEST_REDIS_URL`
    - `AGENTLY_SKILLS_RUNTIME_TEST_PG_DSN`
- **Test Steps**：
  1. 运行 `python -m pytest -m integration -q tests/test_integration_sources_redis_pgsql_smoke.py`
  2. 观察 `SkillsManager.scan()` 是否成功（允许 scan 结果为空）
- **Expected Results**：
  - 测试通过（无异常）
- **Postconditions**：无

### 2. Edge Case Tests

#### TC-E-001: DSN 未配置时给出明确 skip 指引
- **Requirement**：integration 用例允许 skip，但必须可诊断且可复刻
- **Priority**：Medium
- **Preconditions**：
  - 未设置 `AGENTLY_SKILLS_RUNTIME_TEST_REDIS_URL` / `AGENTLY_SKILLS_RUNTIME_TEST_PG_DSN`
- **Test Steps**：
  1. 运行 `python -m pytest -m integration -q tests/test_integration_sources_redis_pgsql_smoke.py`
- **Expected Results**：
  - 用例被 skip
  - skip message 指向本仓库的一键复刻脚本（docker + migration）

### 3. Error Handling Tests

#### TC-ERR-001: 缺少可选依赖（redis/psycopg）时给出明确 skip 指引
- **Requirement**：缺依赖时允许 skip，但必须明确如何安装
- **Priority**：Medium
- **Preconditions**：
  - 未安装 `redis` 或 `psycopg`
- **Test Steps**：
  1. 运行 `python -m pytest -m integration -q tests/test_integration_sources_redis_pgsql_smoke.py`
- **Expected Results**：
  - 用例被 skip
  - skip message 提示安装缺失依赖（示例命令/包名）

## Test Coverage Matrix

| Requirement | Test Cases | Coverage Status |
|---|---|---|
| requester 最小契约（不打外网） | TC-F-001 | ✓ Complete |
| redis/pgsql sources scan 冒烟 | TC-F-002 | ✓ Complete（有环境） |
| 缺 DSN 的可诊断 skip | TC-E-001 | ✓ Complete |
| 缺依赖的可诊断 skip | TC-ERR-001 | ✓ Complete |

## Notes
- `-m integration` 的目标是 “dev-ready 可复刻”，而不是保证在无环境的机器上必跑通过；无环境时必须 skip 且给出复刻路径。

