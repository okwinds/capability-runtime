# 如何将此 Prompt 投递给 Codex CLI

## 方式一：直接使用（推荐）

将 `CODEX_PROMPT.md` 放到仓库根目录，然后：

```bash
cd /path/to/agently-skills-runtime

# 将 CODEX_PROMPT.md 复制到仓库根目录
cp CODEX_PROMPT.md ./CODEX_PROMPT.md

# 使用 codex cli 执行
codex --model claude-sonnet-4-20250514 \
  "请阅读仓库根目录的 CODEX_PROMPT.md，这是完整的重构指南和规格。严格按照文档中的步骤顺序实施重构。先读完全文再开始编码。"
```

## 方式二：通过 AGENTS.md（如果你的仓库支持）

将 `CODEX_PROMPT.md` 的核心内容放到仓库根目录的 `AGENTS.md` 中，Codex 会自动读取。

```bash
cp CODEX_PROMPT.md ./AGENTS.md
codex "按照 AGENTS.md 的规格实施框架重构"
```

## 方式三：分阶段执行（更可控）

如果你担心一次性投递太多，可以分阶段：

### Phase 1: Protocol 层
```bash
codex "阅读 CODEX_PROMPT.md。只执行 Step 1: 创建 protocol/ 目录，实现所有 6 个协议文件，并为 protocol/ 编写单元测试。"
```

### Phase 2: Runtime 层
```bash
codex "阅读 CODEX_PROMPT.md。执行 Step 2: 创建 runtime/ 目录（registry, guards, loop, engine），并编写对应测试。"
```

### Phase 3: Adapters 层
```bash
codex "阅读 CODEX_PROMPT.md。执行 Step 3: 创建 adapters/，迁移 llm_backend.py，实现三个适配器。"
```

### Phase 4: 整合 + 测试
```bash
codex "阅读 CODEX_PROMPT.md。执行 Step 4-6: 更新入口文件、编写 scenario 测试、清理旧代码。"
```

## 文件清单

你只需要向 Codex 提供一个文件：

| 文件 | 用途 | 放置位置 |
|------|------|---------|
| `CODEX_PROMPT.md` | 完整重构指南+规格 | 仓库根目录 |

CODEX_PROMPT.md 已经包含了所有必要信息：
- 项目背景和核心理念
- 仓库现状和处置决策（哪些保留、哪些推倒）
- 新架构的完整包结构
- 每个文件的详细接口规格（含代码级定义）
- 实施步骤顺序
- 关键约束和验收标准

**不需要额外提供其他文件。** 框架是通用的，不绑定业务，所以业务相关文件（BP、Excel、DAG 等）不需要给 Codex。Codex 需要的一切都在 CODEX_PROMPT.md 里。

## 注意事项

1. **确保 Codex 能访问仓库代码**——它需要读取现有的 `adapters/agently_backend.py` 来迁移

2. **上游依赖**——仓库的 pyproject.toml 声明了 `agently` 和 `skills-runtime-sdk-python` 作为依赖。Codex 在运行测试时可能需要这些包。如果安装有问题，告诉 Codex "上游可以 mock，专注于框架自身代码和测试"

3. **如果 Codex 输出太长中断**——用分阶段方式执行

4. **代码风格**——CODEX_PROMPT.md 中给出的代码片段是接口规格，不是完整实现。Codex 需要补充实现细节（错误处理、边界情况等）
