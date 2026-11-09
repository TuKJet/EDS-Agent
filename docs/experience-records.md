# 统一工程经验记录

项目目录保存研究原貌；个人数据根的 `knowledge/iterations/` 保存可复用的迭代经验投影。
后续任务按当前问题检索经验，不需要逐个打开历史项目目录。项目里的 `study.json` 仍然是
事实来源，中央记录携带固定版本、来源哈希和必要快照；删除或迁移项目副本后，中央记录
仍可被读取并重建索引。

## 什么会进入中央库

每轮形成 `assessment` 后，保留一条模型无关的 `feedback` 记录。它既覆盖工具执行迭代，也覆盖
论文方法论和参数优化讨论。它至少区分当前目标与约束、采用的方法/路线和端点、预期与实际观测、
失败状态、修复动作、验证证据、适用边界，以及后续任务对它的采用、限制或拒绝结果。方法评估
还要保留方法固定版本、产品特征和工况、参数变化、baseline/candidate 指标和改善/劣化/无改善/未验证状态。

方法评估使用 `method_evaluations` 保存固定方法知识引用、产品特征、工况、参数变化、
baseline/candidate 对比、效果状态、证据来源（`literature`、`runtime` 或 `inference`）和限制。
没有 Run 时可以是文献评估或推断。文献评估可以记录论文报告的 `improved` 或 `degraded`，
但 `evidence_origin="literature"` 不等于当前产品的 runtime 复验；`inference` 只能保持
`inconclusive` 或 `not_tested`，不能独立声称已测试的方法效果。不能把论文表格直接当作当前
产品的实测改善。

指导状态使用 `unverified`、`verified` 或 `invalidated`。`verified` 必须有固定的验证引用，
并且不能包含 `unknown`、`planned`、`submitting`、`submitted` 或 `running` 的 Run；这些状态只能
留下未决经验。方法评估的效果另用 `improved`、`degraded`、`mixed`、`unchanged`、`inconclusive`
或 `not_tested` 表示。论文可以报告 `improved`，但 `evidence_origin="literature"` 不等于当前
产品的 runtime 复验。
一次工具调用完成也不等于工程结论成立；论文中的效果声称也不等于当前产品已经改善。

基础迭代记录不受 `once/auto/later/skip` 影响；这些选项只控制是否进一步整理成人或 Agent 提出的
高层经验。归纳失败不会删除已经保存的迭代记录，中央写入或索引失败会保留待重试状态。

## 发布与追溯

对受管 Study 使用：

```powershell
python -m eds study "@study/gearbox" experience-status
python -m eds study "@study/gearbox" experience-publish --knowledge-root "@knowledge"
```

旧的显式 Study 路径可先绑定中央库：

```powershell
python -m eds study D:/legacy/study experience-bind --knowledge-root "@knowledge"
```

旧项目的一次性迁移使用回填入口：

```powershell
python -m eds study D:/legacy/study experience-backfill --knowledge-root "@knowledge"
python -m eds study D:/legacy/study experience-backfill --assessment assessment@2 --knowledge-root "@knowledge"
```

`experience-backfill` 只读原 Study 并写中央库，不在旧 Study 添加 publication/outbox
事件；适合一次性迁移，按 Study 与 Assessment 版本幂等。`experience-bind` 用于绑定未来
迭代，`experience-publish` 用于重试已经跟踪的中央发布。原项目迁移后仍保留其事实记录，
中央经验记录保存引用、哈希和必要快照。

发布按 `study_id + assessment 版本` 幂等；重复发布不会制造重复经验。原始 Study 引用、Run/证据
引用、文件版本和哈希写入中央记录，不能把绝对路径当成可迁移文件。大型 CAD/CAE 文件仍需
放入 `assets/` 或保留外部资产指纹。

## 为未来模型保留的母数据边界

中央经验记录不直接保存某个模型的向量、LoRA 权重或特定 tokenizer 格式。它保留事实、条件、
动作、结果、判断和反例，未来可以从同一母库生成检索单元、n-gram/PLE 查表样本或小基模训练
样本。任何下游投影都必须保留原记录的 `id/version/hash`，并按项目、时间、环境和验证状态
切分，避免把一次失败、个人偏好或未经复验的推断训练成通用规则。

经验命中只产生带条件的候选路线和证据提示；Codex 仍负责判断是否采用，执行端不会因为 n-gram
字面命中而自动改写 MCP 调用。

一个方法评估可以写在 `assessment.payload.experience` 中：

```json
{
  "experience": {
    "status": "unverified",
    "method_evaluations": [
      {
        "knowledge_ref": "method-paper-a@2",
        "product_features": ["thin-wall housing", "long unsupported span"],
        "conditions": {"load": "baseline", "material": "unknown"},
        "parameter_changes": {"rib_pitch_mm": {"baseline": 8, "candidate": 5}},
        "comparison": {"metric": "max_displacement_mm", "baseline": 1.8, "candidate": 1.4},
        "effect": "improved",
        "evidence_origin": "literature",
        "evidence_refs": ["evidence-paper-table@1"],
        "limitations": "reported by the paper; product runtime validation is pending"
      }
    ]
  }
}
```

中央快照按 Assessment 创建时截断 Run 历史；创建时间、环境或版本缺失时明确写成
`unknown`，不会把后来追加的状态倒灌进旧经验。不是每个 CLI 调用或每条聊天都自动生成
LLM 归纳，只有形成实质认识变化的 Assessment 或方法评估才发布经验记录。
