# 运行时检查精简与工程图路由修复

日期：2026-11-04。按用户要求修复独立审查的前四项及工程图任务子 Skill 路由。只做本地验证，不连接 VM/MCP、不执行 CAD/CAE。

## 修改结果

| 项目 | 修改后的行为 |
| --- | --- |
| 重复只读观察 | 绑定明确声明 `read_only: true` 后，已完成观察可同参数再次调用，创建新 Run 并取得新结果。未声明时维持有副作用语义。 |
| 未发送失败重试 | 明确 `failed + preflight_rejected=true + tool_sent=false` 的请求可修复后显式重试；保留失败历史，重试准备中断也可接续。每次调用最多发送一次。 |
| 日常执行预检 | `execution --capability <name>` 只查指定能力及必要查询工具；不指定时查绑定已声明能力，不要求全域四项齐备。普通路径不读 Git、不重放补丁、不检查另一域。 |
| 显式维护 | `--maintenance` 才检查所选域的固定提交、工作树和补丁；`--full` 仅扩展输出。`install-skills --execution none` 只同步 EDS Skill，不检查执行子模块。 |
| 日常知识读取 | 普通 search/read 不执行全库派生结构审计或 SQLite 全页检查。search 对登记源做一次文件状态检查，只校验返回源；定点 read 不因无关源编辑而阻塞。 |
| 知识维护 | `status/sync/rebuild` 保留完整索引检查。选中源正文与 metadata 仍校验；关系直接来自选中 Markdown。方法检索不加载无关偏好图。 |
| 工程图入口 | 出图、3D 转 2D、图内 BOM 先读真正的 `solidworks-engineering-drawing/SKILL.md`，再按需读 schema/API；独立 BOM CSV 导出仍走导出参考。 |

针对同一动作的 pending/unknown 防重、已执行变更的重复提交限制及既有实验预算仍保留。没有引入自动重试、全局工具锁、新依赖或新的执行实现。只读属性来自已核对语义的绑定，不靠工具名猜测。

源文件新鲜度的轻量检查使用大小与修改时间；所选结果仍读取源文件并核对 hash/正文。完整派生索引一致性属于显式维护，不承诺每次检索都检测所有缓存损坏或保留时间戳的外部篡改。

## 本地证据

- 完整回归 **183/183 通过**（191.743 秒）：[unittest.log](../workspaces/validation/lightweight-20261104/unittest.log)。覆盖只读新观察、绑定/非绑定未发送重试、准备中断恢复、变更防重、目标能力检查与维护隔离、知识来源验证及显式深审计。
- 编译检查：[compile.json](../workspaces/validation/lightweight-20261104/compile.json)。
- 四个 Skill 格式检查：[skill-format.json](../workspaces/validation/lightweight-20261104/skill-format.json)。
- 安装副本已同步，显式维护检查 `in_sync=true`，CAD 既有五补丁为 `applied`、CAE 无需补丁：[install-check.json](../workspaces/validation/lightweight-20261104/install-check.json)。
- 独立工程图路径演练：[drawing-route.md](../workspaces/validation/lightweight-20261104/drawing-route.md)。成功定位剖视图/孔表的实际能力限制，未调用生成器。

## 边界

本轮没有改变执行端源码补丁或部署状态，没有重新做实机工程验收。历史 AC-07 待执行、AC-10 用户跳过的状态保留。Study 大记录/恢复存储优化、上游工程图审查默认项精简不在本轮范围内。
