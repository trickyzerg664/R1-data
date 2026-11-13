# 实际验证结果（2026-11-13）

## 新环境与搬移

- 固定 CPython 3.10.16 + 35 个锁定运行依赖，不继承系统 site-packages。
- pip check：No broken requirements found。
- 实测 PyTorch 2.5.1+cpu、FAISS 1.9.0.post1、NumPy 1.26.4、Transformers 4.46.3。
- 独立新目录、不复制 .env、无 API Key、无 .venv，一次命令建环境并完成 self-test。
  使用已下载 wheel 缓存离线安装；公共依赖下载另已成功执行。
- 环境包解压到另一目录后 start.sh --self-test 通过，使用包内 Python 3.10.16。
- 故意设置不可用 PYTHONPATH，Python -I 隔离成功。
- 最终额外验证：PATH 不含任何系统 Python，只放 Linux shell 工具和环境压缩包，
  `bash start.sh --self-test` 自动校验 SHA256、解压包内 Python 并通过全流程。

## 本地 HTTP 全流程

3 条合成 fixture 合格；6 次本地 HTTP 教师请求；3 次实际 FAISS Flat 库检索；
再次处理完成题不新增请求；生成 JSONL、stats、ZIP，完成本地收件。
实际启动、等待和清理 Retriever 子进程，外部教师调用 0。
fixture 使用哈希向量和合成文档，输出隔离保存，不作为正式语料。

## 完整真实检索

start.sh --retriever-smoke **通过**：完整加载 64559075373 字节、768 维、21015324
个向量的 Flat IP 索引；实际加载 E5；扫描验证语料行数与索引一致；搜索
“What is the capital of France?” 返回 3 份真实文档并清理子进程。教师调用 0。
实际结果在本地 output/retriever_smoke.json，不提交 Git。

## 恢复测试

独立 Python 3.10.16：**15/15 通过，1.092 秒**。
覆盖多轮、429 等待、额度耗尽停止并触发上传、401 不无限重试、单题错误继续、
子进程退出暂停教师、中断恢复、上传失败保留文件、异工作目录启动、超时 uncertain、
崩溃 pending 恢复、空检索合法，以及 DeepSeek 402/请求参数处理。

## 数据与环境分发

- 候选题 169594：NQ 79159，HotpotQA 90435；排除评测重叠 10、重复 11。
- 候选 gzip 11718860 字节；输入/输出 SHA256 见 data/manifest.json。
- 环境包 259602238 字节，SHA256：
  c488d69bb51927d5f065f9276e9133ff6fe7d460e87c520c9130717ea3515e75。
- 环境包和依赖锁实际上传 HF private 仓库 tr1ckyzerg/R1-sft 的 runtime/，
  commit 628f7d3ef703aed44eaae8deff4d14a6276d72f7。
- .env 和凭证未进入 Git 或环境包。

## 限制

- 没有真实 DeepSeek Key，未调用付费 API，未验证教师实际格式遵从率。
- 未生成正式 3000 条轨迹，未把 fixture 当正式数据上传。
- 未在全新设备重下载约 80 GB 资源；本轮复用既有资源。
- 环境包仅在 Linux x86_64、glibc 2.35 实测，不含 CUDA；其他平台未经验证。
- 当前 host 的 HF DNS 解析异常，上传使用 host3 已有代理，未修改系统 DNS。
