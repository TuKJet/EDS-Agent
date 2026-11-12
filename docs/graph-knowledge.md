# SQLite + GraphQLite 知识检索

EDS 的知识源仍是可同步的 Markdown、JSON、`registry.json` 和 Study 记录。
现有 `index.sqlite3` 继续负责 FTS5 词法检索、固定版本读取、关系元数据、源文件哈希和
新鲜度校验。GraphQLite 只是可选的本地图投影，生成在同一缓存目录中的 `graph.sqlite3`；
它提供关系、条件和方法效果的有界路径检索，不成为第二份事实来源。

## 安装与平台

核心记录和普通检索只依赖 Python 标准库。需要图检索时，在项目或用户自己的隔离环境中执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pip install -r requirements-graph.txt
python -m eds doctor --graph
```

macOS/Linux 使用 `source .venv/bin/activate`，然后用 `python` 执行同一组命令。后续图命令
默认在这个已激活的虚拟环境中运行；也可直接用 `.venv` 内的 Python 代替命令中的 `python`。
所用 Python 的 SQLite 必须支持加载扩展，`doctor --graph` 会实际检查这一点。
当前依赖固定为 `graphqlite==0.9.4`，
属于可选、Beta 级扩展；GraphQLite 官方安装文档和 PyPI 页面列出的 wheel 覆盖 Windows
x64、Linux x64/ARM64 及 Apple Silicon macOS。0.9.4 在 PyPI 上没有 Intel Mac 预编译
wheel，可能需要源码构建，因此不能把 Intel Mac 视为已验证安装路径：

- [GraphQLite 0.9.4 on PyPI](https://pypi.org/project/graphqlite/0.9.4/)
- [GraphQLite installation](https://colliery-io.github.io/graphqlite/how-to/installation/)

项目当前只对 Windows x64 的 Python 3.14.4、SQLite 3.50.4 做过实际加载与查询探针。
Linux/macOS 的平台说明用于安装规划，不替代目标机器上的 `doctor --graph` 验证。

## 维护本地图缓存

先维护普通索引，再显式构建图：

```powershell
python -m eds kb <knowledge-root> graph-sync
python -m eds kb <knowledge-root> graph-sync --force
python -m eds kb <knowledge-root> graph-status
```

`graph-sync` 先同步注册的 Markdown 到 `index.sqlite3`，再校验中央经验 JSON 的固定身份和哈希，
在临时图缓存中重建投影并原子替换 `graph.sqlite3`。普通 `sync`/`rebuild` 可用 `--graph`
显式同时维护图；不加该开关时不会隐式创建图。每次 Study、Assessment 或预设操作也不会
自动查询或更新图，以免把高频执行路径变成重复检索。

图状态单独报告依赖可用性、缓存是否存在、源指纹和过期原因。`graph-status` 是诊断命令，
即使依赖缺失或缓存过期也返回状态；`graph-search` 会拒绝使用无效图，`graph-sync` 则负责
创建或修复图，缺少依赖时提示安装。普通 `kb search`、`read` 和 FTS5 路径仍然可以工作。

## 选择图检索

只在问题需要关系结构时使用图，例如“哪些方法在相同边界条件下被验证过”“某参数变化导致
哪些正面或负面效果”“某条证据与哪些反馈有关”。先用 FTS5 找到种子，再做深度有限的图路径：

```powershell
python -m eds kb <knowledge-root> graph-search "边界条件" --question method-selection --depth 2 --max-nodes 100
python -m eds kb <knowledge-root> graph-search "压力" --relation supports --relation contradicts --domain cae
```

深度限制为 0–3，节点预算限制为 1–100；种子最多 5 个，边预算为节点预算的 4 倍，
达到预算或结果上限会返回 `truncated`。结果包含固定 `id`、`version`、源路径、哈希、
关系路径、独立方法评价和未解决的固定版本引用。路径中的节点键可在结果的 `nodes` 中
解析为原始身份，边始终保留声明方向。通过普通 `read` 校验路径上的源记录；路径是候选证据，不自动表示因果关系、采用建议
或实验通过。`supports`、`limits`、`contradicts` 和 `related_to` 等关系保留原样，正面、
负面、混合和未定结论分别保存在经验记录中，不会被图投影合并覆盖。

图来自知识单元已有的 `relations`，以及中央经验 JSON 中的 `method_evaluations`。
每项评价单独连接所属经验和固定版本方法，并保留产品特征、条件、参数变化、对照、效果、
证据来源与限制。没有这些记录时，图可以只有独立节点；系统不会自动从文章或历史对话中
推断关系。相似条件和适用性仍需 Codex 根据原始证据判断。

查询先检查源文件状态，再对实际经过的知识单元和经验 JSON 校验内容哈希；不会在每次
查询时重读全部大型经验快照。`graph-status` 和图构建执行完整源哈希审计。项目、域和
问题类型的筛选同时约束中间路径；缺失引用不能充当连接其他记录的桥梁。`--relation`
严格限制边类型，若要包含方法评价路径，需要选择 `has_evaluation`、`evaluates_method`
或不指定关系筛选。

个人/团队 `preference` 单元不进入工程图；绘图风格等高频习惯继续通过活动预设的“当前版本、
任务内覆盖、保存为默认”路径提供。图查询也不暴露任意 Cypher 写入口，避免把关系缓存变成
未审计的公共写库。

## 跨电脑同步边界

只同步个人数据根目录中的源记录、预设、Study 和明确选定的附件。目标电脑执行：

```powershell
python -m eds data use <root>
python -m eds kb "@knowledge" sync
python -m eds kb "@knowledge" graph-sync   # 需要关系检索时
```

SQLite/GraphQLite 文件、锁、临时文件、凭据和 VM 绑定留在本机或重建；不要把它们当作多机
合并格式。并发编辑同一 Study 或偏好版本仍需人工处理，GraphQLite 不提供远端同步或冲突合并。
