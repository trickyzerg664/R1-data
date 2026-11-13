# 验证结果（2026-11-13）

目标环境：用户指定的远程容器，Python 3.10.12。未安装/升级该容器的全局依赖。

## DeepSeek / HF 配置更新后的验证

HF 目的仓库已配置为 `tr1ckyzerg/R1-sft`；教师预设 `deepseek-flash`，
`thinking.type=disabled`，官方 Base URL 已填入 `.env.example`。

最终容器测试：**15/15 通过，0.994 秒**。在下方原有 13 项测试基础上增加：
DeepSeek HTTP 402 即使没有错误正文也停止并触发上传；请求明确传入 disabled thinking，
同时保留教师实际返回的标签内容。原有错误恢复测试全部通过。

`main.py --check`：候选题与既有资源结构检查通过，
`teacher_model_configured=true`、`upload_repo_configured=true`。

运行环境仅检查凭证是否存在，不输出值：本项目未检测到 API_BASE_URL、API_KEY、HF_TOKEN。
当前系统 Python 可找到 torch、transformers、fastapi、uvicorn、huggingface_hub，找不到 faiss。
Git origin 已关联用户指定的 R1-data 仓库；没有 commit/push。
未调用真实教师 API、未发起 HF 上传，未启动完整真实 Retriever。

后续本地授权更新：已将 HF_TOKEN 写入运行机器 `.env`，文件权限 600，Git 忽略；
未配置教师 API Key。再次执行全部 15 项离线测试通过（0.908 秒），Mock 模式无需 Key 可运行。
此配置只在本地，不随源码和候选题推送。上述“未检测到凭证”为首次检查记录。

## 首版骨架验证记录

`python3 -m unittest discover -s tests -v`：**13/13 通过**（最终版本，0.827 秒）。

覆盖：Mock 多轮和目标停止、429 Retry-After、额度耗尽保存并触发上传、401 不重试、
单题格式失败不影响后题、真实短命子进程退出后阻止教师调用、中断后从检索阶段恢复、
上传失败保留文件和仅重传、异工作目录启动、超时有限重试并标记不确定、崩溃 pending
标记 uncertain、空检索合法、普通 429 与明确额度不足分类。

`main.py --check` 从其他工作目录执行：通过。

- 候选题：169594（NQ 79159，HotpotQA 90435）。
- 过滤：输入 169615；排除评测重叠 10、重复问题 11。
- 候选 gzip：11718860 字节；SHA256
  `ca28cf1d39aefd4727f01dfde9096cfb9eddab9764895d8170e7c664fc6428b6`。
- 输入 parquet SHA256 与原资产清单一致。
- 现有索引头、长度检查通过：Flat IP，768 维，21015324 个向量，64559075373 字节。
- 现有语料首行结构通过：14393573105 字节。
- E5 配置、权重及 tokenizer 文件存在。
- 教师模型 ID、HF 目的仓库均未配置，检查结果明确报告 false。

`main.py --mock` 从其他工作目录执行：3 条合格 fixture，6 次 Mock API，3 次 Mock 检索，
停止原因 `target_reached`；独立保存在 `output/mock/output/`。

## 尚未验证

- 没有调用真实付费 API，Mock 调用数不是实际 API 账单。
- 没有发起真实 Hugging Face 上传；上传成功/失败行为通过替身验证。
- 没有加载完整 64.6 GB FAISS 索引或启动完整真实 Retriever。
- 现有大型资源未重新完整计算 SHA256；清单保留原下载流程的历史校验值。
- 没有实际执行首次大文件下载，也未验证 Mac 的依赖安装和内存承载能力。
- 没有 Git commit 或 push，未修改原 Search-R1 项目及共享资源。
