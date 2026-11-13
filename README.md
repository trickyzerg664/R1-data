# Search-R1 synthesis scaffold

独立 Python 数据合成项目，目标为 **3000 条合格轨迹**，不修改 Search-R1 训练代码。
Python 3.10/3.11；不需要 veRL、Ray、vLLM，不使用 Docker 部署本项目。

## 当前可用范围

- 可执行 Mock 多轮流水线和标准库 unittest 恢复测试，无付费 API。
- 真实 NQ/HotpotQA 候选题已打包在 `data/`，保留失败余量，3000 条合格后停止。
- SQLite 每轮保存 API 请求状态、原始响应、上下文、真实检索文档、尝试次数。
- API 临时故障有限退避，区分额度耗尽、配置错误和结果不确定。
- 单题失败最多三次，最多八轮。规则检查标签、唯一动作、真实搜索、重复查询及答案 EM。
- 通过相对链接复用现有 Wiki18、E5 模型和 Flat 索引，无需复制大文件。
- Retriever 骨架使用同一 768 维 CPU Flat 内积索引；编码器可用 CPU/CUDA。
- HF 上传代码已接入，目的地为 `tr1ckyzerg/R1-sft`；运行机器需单独预配授权，真实上传尚未验收。

**当前是待接通真实服务的骨架，不宣称已经完成付费 API 或完整真实检索验收。**

## 快速验证

```bash
python3 -m unittest discover -s tests -v
python3 main.py --check
python3 main.py --mock
```

`--mock` 仅使用合成 fixture，写入 `output/mock/output/`，不混入真实数据。
脚本从其他工作目录启动时，仍按脚本所在项目根目录解析资源路径。

## 后续真实启动

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# 协作者只编辑 API_BASE_URL 和 API_KEY
python main.py
```

`API_BASE_URL` 默认模板使用 DeepSeek 官方 `https://api.deepseek.com`。
程序在其后追加 `/chat/completions`。维护者已预设 `teacher.model=deepseek-flash`，
`thinking.type=disabled`，由模型在实际 `content` 中输出 Search-R1 标签；不拼造推理内容。
完整原始响应仍会保存。若后续改为原生 thinking 模式，需要另行适配 `reasoning_content`。
HTTP 402 按 DeepSeek 官方定义识别余额不足，401 立即停止，429 和 5xx 有限退避。
官方依据：https://api-docs.deepseek.com/ 、https://api-docs.deepseek.com/guides/thinking_mode/
以及 https://api-docs.deepseek.com/quick_start/error_codes/ 。

`retriever.*_revision` 已按现有资源清单固定；首次下载使用 Hugging Face 分片下载，识别
语料实际 tar.gz 格式后只读取唯一 JSONL 成员，并做 SHA256 校验。现有资源通过结构检查后复用，
`assets.json` 保存版本、大小及历史校验值。

## 复用已有资源与候选题打包

```bash
python3 scripts/link_assets.py --assets ../../data/search-r1
python3 scripts/bundle_candidates.py --assets ../../data/search-r1
```

上面的资产目录参数相对项目根目录解析，仅为当前目录布局的维护命令。
源码和配置不写入开发机器绝对路径。`cache/` 中的链接不进入 Git；协作者新机器
会使用项目内下载缓存。外部共享资源只读复用，不删除、不覆盖。

候选题打包需要 `requirements-data.txt` 中的 `pyarrow`（维护阶段，可复用已有环境；运行生成不需要）。
`data/manifest.json` 记录输入与输出 SHA256、来源、过滤规则和各来源数量。
候选池全部保留，不承诺失败率过高时仍一定得到 3000 条合格数据。

## 输出与恢复

`output/` 包括 `state.sqlite3`、`trajectories.jsonl`、`accepted.jsonl`、
`rejected.jsonl`、`api_calls.jsonl`、`stats.json`、`result.zip`、`upload_receipt.json`。
轨迹文件包含标准答案、实际教师消息、失败尝试和真实 observation。标准答案不进入请求。
`processed` 是最终接受/拒绝的题数，`rejected` 是尝试耗尽的题数，失败尝试另留在 history。

正常结束、额度耗尽、Ctrl+C 或全局错误均尽力导出及上传。下次自动恢复。
崩溃前 pending 的请求标为 uncertain，可能已经计费；恢复时可能重发，无法保证零重复计费。
只有服务商明确支持时才填写 `teacher.idempotency_header`。所有 HTTP 重试都计入 API 请求次数。
不设置总请求数、费用上限；当前轮次和每题重试仍有上限。
断电、SIGKILL 或磁盘写满时无法保证即时导出/上传，已提交 SQLite 数据尽力在重启后恢复。
修改数据包、模型或轨迹规则时须保留旧输出，开始新的独立状态，避免混合实验。

## Hugging Face 上传（待维护者配置）

目的地已预设为 private **Dataset** 仓库 `tr1ckyzerg/R1-sft`。直接上传需要运行环境中的
`HF_TOKEN`，仅限目标仓库写权限，不提交仓库，不复用教师 Key，不自动创建远端仓库。
如必须保持协作者只填写两项，需要维护者另行提供预授权环境/上传接收服务；本骨架没有
搭建接收服务，也没有把永久 HF Token 放入代码。

`.env` 不随 Git 分发。当前机器已配置的授权不会自动出现在协作者机器上；可以由维护者
事先在对方机器配置 HF_TOKEN，或让可信协作者单独配置一次。不要将 Token 写入源码或模板。

```bash
python main.py --upload-only
```

上传按 `runs/<run_id>/` 隔离。上传包中的统计描述上传时快照（pending）；本地统计及
`upload_receipt.json` 记录最终结果，避免上传后反复重打包、递归更新归档。失败重传不重新生成。

## Git 内容

应提交源码、测试、README、配置模板、`data/candidates.jsonl.gz` 和 `data/manifest.json`。
不要提交 `.env`、缓存、模型、索引、SQLite、生成输出或永久 Token。此项目尚未 Git commit/push。

## 尚待接通

1. 在实际 Linux 运行环境配置 DeepSeek API Key 和 HF_TOKEN，不提交 Git。
2. 独立安装/验证检索依赖（当前系统 Python 未发现 faiss）。
3. 已有资源只做头部/结构检查，完整索引加载、语料行数和实际检索在首次真实启动验证。
4. 凭证齐全后做少量真实多轮生成及 HF 上传验收；目前只有离线测试结果。

不进行大规模付费测试。默认真实配置未补齐时会明确停止，已有输出仍保留。
