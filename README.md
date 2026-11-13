# Search-R1 synthesis

独立 Linux Python 项目，目标为 **3000 条合格轨迹**。不安装 veRL、Ray、vLLM，
不修改原 Search-R1 训练代码，不使用 Docker 分发。

## 一键启动

在项目根目录准备 `.env`（复制 `.env.example`），填写 DeepSeek Base URL 和 API Key。
HF_TOKEN 由维护者事先配置在运行机器，或由可信协作者配置一次，不提交 Git。

```bash
bash start.sh
```

也支持 `python3 main.py`。首次启动使用配套环境或自动创建隔离 `.venv`、安装固定依赖，
随后准备资源、启动 Retriever 并生成数据。后续复用环境、资源和 SQLite 进度。
自动建 `.venv` 需要 Python 3.10/3.11 和 venv/ensurepip；缺少时使用下方配套环境包。

## 无 API Key 自检

```bash
bash start.sh --self-test
```

实际经过本地 HTTP 教师接口、检索子进程、FAISS Flat 库、动作/答案验收、每轮保存、
断点跳过、JSONL/ZIP 导出和本地收件。使用明确标注的合成文档和哈希向量，不调用外部
教师或 HF，不需要 Key。输出隔离在 `output/self_test/<id>/`，不作为正式数据。

```bash
python3 main.py --mock                  # 标准库轻量测试
python3 main.py --check                 # 候选题与资源结构检查，不下载
bash start.sh --retriever-smoke         # 加载完整真实索引，搜索一次，无教师调用
runtime/python/bin/python3 -I -m unittest discover -s tests -v
```

## 配套 Python 环境包

包含 **Python 3.10.16 和全部运行依赖**，约 260 MB，Linux x86_64、glibc 2.35 已实测。
PyTorch 为 2.5.1+cpu，FAISS 为 CPU Flat，保持搜索算法；此通用包不包含 CUDA。

[下载环境包（Private HF，需要授权）](https://huggingface.co/datasets/tr1ckyzerg/R1-sft/blob/628f7d3ef703aed44eaae8deff4d14a6276d72f7/runtime/runtime-linux-x86_64-py310-cpu.tar.gz)

将压缩包放在项目根目录，运行 `bash start.sh --self-test`，脚本校验 SHA256、解压并
使用包内 Python，无需系统 Python 或手动激活。若已预配置 HF_TOKEN，脚本可自动下载。
`.env` 不随 Git 分发；单纯拉代码不会获得私有仓库下载/上传权限。

`runtime-manifest.json` 固定下载 revision、SHA256、大小；`requirements-linux-cpu.lock`
固定全部实测依赖。环境包不含 `.env`、凭证、问题、模型、语料、索引和生成输出。
环境大包放 HF，源码 Git 仅放脚本和清单。

## 资源和候选题

采用 Wiki18、intfloat/e5-base-v2、768 维 FAISS Flat IP、Top-k=3。首次下载到 `cache/`，
合并索引分片，读取语料 tar.gz 中唯一 JSONL，并校验 SHA256。索引约 64.6 GB，语料约
14.4 GB；推荐 128 GB 内存，首次准备预留约 180 GB 磁盘。自检和环境包不下载大索引。

host3 资源通过项目内相对链接复用，不复制或覆盖共享文件。维护命令：

```bash
python3 scripts/link_assets.py --assets ../../data/search-r1
python3 scripts/bundle_candidates.py --assets ../../data/search-r1
```

参数相对项目根目录解析；重建候选包才需要 requirements-data.txt 的 pyarrow。
`data/candidates.jsonl.gz` 已随 Git 打包：169594 题，约 11.7 MB。去掉空问题/答案、
重复问题和提供的评测集中重叠问题，NQ/HotpotQA 交错。来源、版本、SHA256 见 manifest。
3000 是合格目标；候选全部耗尽仍不足时按实际数量结束。

## 教师与验收

默认 https://api.deepseek.com、deepseek-flash，关闭原生 thinking，由实际正文输出
`<think>` 和唯一 `<search>`/`<answer>` 动作。不拼造推理或检索结果，完整保存响应。
标准答案只在本地判分，不进入教师上下文。原生 reasoning_content 模式尚未接入。

每题最多三次尝试，每次最多八轮，至少一次真实搜索，不允许重复查询。答案规范化
小写、英文标点、冠词及空白后，与任一答案别名完全匹配。规则无法保证推理/证据
使用正确，仍需抽查。没有总请求量或费用上限。

DeepSeek 402 识别余额耗尽；401/配置错误停止；429/5xx 有限退避并遵守 Retry-After。
超时标记 uncertain，不承诺零重复计费；幂等头仅在服务商明确支持时开启。

## 保存、恢复和上传

每轮响应及检索结果提交 SQLite，重启自动恢复并跳过成功/耗尽尝试的题。
`output/` 包括 state.sqlite3、trajectories.jsonl、accepted.jsonl、rejected.jsonl、
api_calls.jsonl、stats.json、result.zip、upload_receipt.json。
结束、中断或错误时尽力导出/上传；断电/强制终止需下次恢复。

模型临时错误重试耗尽、永久配置错误或其他无法恢复的全局错误，会停止新教师调用，
先保存并导出已有结果，再上传。`accepted.jsonl` 只包含已经通过规则验收的轨迹，
未完成/拒绝内容仅留在审计文件；上传成功后也不删除本地文件。

目的地为 private Dataset `tr1ckyzerg/R1-sft` 的 `runs/<run_id>/`，需要本地 HF_TOKEN。
不自动建远端仓库，上传失败保留文件。已有正式结果重传：

上传超时、网络故障、429 和 5xx 默认最多尝试 5 轮，指数退避和随机抖动，优先遵守
Retry-After；401/403/404 等永久错误不反复重试。默认连接/读取超时 10/120 秒。
参数由维护者配置在 `upload` 节中，不需要协作者调整。

重试耗尽或上传中断会把待重传状态写入 SQLite。再次普通启动时，**先补传，再恢复生成**；
补传仍失败就退出，避免继续付费调用。重传使用相同 run_id 目录，不重新生成已完成题。
若服务端已提交而响应丢失，可能出现额外 HF 提交，但不会创建另一份题目记录。

```bash
bash start.sh --upload-only
```

上传包中 stats 为上传时快照，本地 stats/receipt 记录最终状态。完整真实索引搜索、
新环境安装/搬移和 HF 环境包上传已验证；尚未调用付费教师，也未在新机器重新下载
约 80 GB 资源。实测细节见 TEST_RESULTS.md。

退出码：0 为生成正常结束且上传完成（或无数据/明确测试模式）；2 为生成侧异常；
3 为数据仍待上传。无生成数据时不向 HF 上传空批次。上传失败时仍保留原始停止原因。

资源校验完成后在 cache/resource-verification.json 保存文件状态；未变化时快速复用，
文件变化后重验 SHA256，校验失败不能通过重启绕过。首次升级现有缓存会全量读一次资源。

网络限制：当前 host3 容器直连 HF 超时，宿主机已有代理可访问仓库。自动重传不会解决
持续不可达的网络，需要在运行机器配置可用的 HTTPS_PROXY；本项目不硬编码开发机代理地址。
