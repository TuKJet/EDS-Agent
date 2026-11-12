# 既有产品接管

产品接管用于在启动新的 CAD/CAE Study 前，整理一个已经存在的产品现状。
它采用渐进式流程：先接收用户提供的图纸和文字，再固定来源版本、记录已知事实
与缺口，最后从固定基线派生 CAD/CAE Study。它不会补写未记录的历史实验，也不会
凭二维图纸重建未保存的三维特征树、网格、求解设置或隐藏设计意图。

## 用户如何使用

用户只需要提供文件并用自然语言说明已知信息、目标和疑问；不需要填写 JSON，
也不需要一次性完成详尽表单。Codex 会把对当前步骤有用的信息整理成 CLI 所需
的 JSON。只询问会阻塞当前工作的缺口，其余未知项先记录为 gap，并继续处理
独立可用的信息。

原始文字应尽量保留：可以直接附加 `.txt`/`.md`，或在声明中保留文件 URI、页码、
图号、段落等 locator。图纸事实可以来自可读的 PDF/文本或用户明确选定的后端回读；
这不表示系统自动 OCR、完整解析所有 CAD 格式，或能够推断未显示的设计意图。

## 数据边界与版本

产品是私有 EDS 数据根目录中的记录，`@product/<id>` 解析到
`studies/products/<id>`。ProductStore 复用现有的版本化 StudyStore 设计，不新增
数据库，也不改变现有 manifest 格式。选定的源文件按内容哈希复制到：

```text
assets/products/<source Study id>/<hash>/<name>
```

产品基线是有版本的接管视图；原有 Study 仍是其自身工程事实的来源。绑定到基线的
源修订不可静默改变。若用同一个 `asset_id` 替换文件，会产生新的资产/基线修订，
但保留旧声明所引用的旧文件哈希；旧声明不会被改写成新文件的事实。

同一个受管数据根目录整体迁移到另一台电脑时，产品的相对引用保持可移植；迁移后
仍需检查文件哈希。若产品基线被另一个数据根或根外的 Study 引用，则记录绝对 source root，并标记
`requires_rebind_on_move`；移动后不会自动重映射，必须重新绑定并重新解释相关声明。

## 完整示例：gearbox

下面示例假定已经按[个人数据根说明](personal-data.md)初始化并绑定个人目录。
用户先说“这是 gearbox 的现有图纸，我再补充一份说明；图纸里能确认
外形尺寸，材料暂时未知”。Codex 只把这些信息写入相应声明和缺口。

### 1. 初始化空基线

```powershell
python -m eds product "@product/gearbox" init --product-id gearbox --name "Gearbox"
```

这会建立空的 `product-baseline@1`。之后每次 attach/update 都以明确的 `--base`
创建新基线。

### 2. 附加现有图纸与用户说明

```powershell
python -m eds product @product/gearbox attach drawing.pdf `
  --asset-id gearbox-drawing --role drawing --base product-baseline@1

python -m eds product @product/gearbox attach notes.md `
  --asset-id gearbox-notes --role text --base product-baseline@2
```

现在分别得到 `product-baseline@2` 和 `product-baseline@3`。如果 `notes.md` 是
用户原话，声明应保留其 locator 和原文，而不是只保留 Codex 的改写。

### 3. 用自然语言生成声明与缺口

用户可以说：“图纸第一页主视图标了总长 120 mm；我认为材料是铝合金，但图纸
没有写牌号。请把尺寸归为 document，把材料意图归为 user，材料牌号列为缺口。”

Codex 将以下数据保存为 UTF-8 文件 `gearbox-intake.json`：

```json
{
  "statements": [
    {
      "id": "overall-length",
      "subject": "housing",
      "topic": "envelope",
      "text": "总长为 120 mm。",
      "attribution": "document",
      "sources": [{"asset_id": "gearbox-drawing", "locator": "第 1 页，主视图"}],
      "value": 120,
      "unit": "mm",
      "validation": "unverified"
    },
    {
      "id": "material-intent",
      "subject": "housing",
      "topic": "material",
      "text": "用户意图为铝合金。",
      "attribution": "user",
      "sources": [{"asset_id": "gearbox-notes", "locator": "原文第 1 段"}],
      "validation": "unverified"
    }
  ],
  "gaps": [
    "图纸和当前说明均未给出可确认的材料牌号。"
  ]
}
```

然后写入 `product-baseline@4`：

```powershell
python -m eds product @product/gearbox update `
  --data gearbox-intake.json --base product-baseline@3
```

`statements` 按 `id` upsert；只有传入 `gaps` 时才替换当前 gaps。声明支持
`document`、`user`、`codex` 三种 attribution。`validation` 默认为
`unverified`；设为 `verified` 时还必须提供独立的 `verification_sources`，每项
形如 `{uri, locator}`，已有的 `sources` 不会自动作为验证通过的依据。这表示来源可追溯性检查，
不表示工程正确性已被证明；Codex 推断不能自动变成 verified。

### 4. 从同一个固定基线建立 CAD/CAE Study

```powershell
python -m eds study "@study/gearbox-cad" init `
  --goal "建立 gearbox 的 CAD 表达" --mode cad
python -m eds study "@study/gearbox-cae" init `
  --goal "评估 gearbox 的结构工况" --mode cae

python -m eds product @product/gearbox use `
  --study @study/gearbox-cad --baseline product-baseline@4
python -m eds product @product/gearbox use `
  --study @study/gearbox-cae --baseline product-baseline@4
```

`use` 返回设计实体，其 `ref` 是目标 Study 内部引用，例如 `product-gearbox@1`；Codex 应将它放入后续
Experiment/Run 输入，以便影响追踪。重复使用同一产品基线是幂等的。显式采用同一
产品的新基线会在目标 Study 中追加新的 design revision；旧 design 和旧 Run 仍固定
在原基线，不会自动跟随最新版本。`use` 不改变目标 Study 的 mode。

### 5. 批量发布并查询知识库

完成一批有意义的接管输入后再发布，不要每收到一句话或一个文件就发布：

```powershell
python -m eds product @product/gearbox publish `
  --baseline product-baseline@4
python -m eds kb "@knowledge" search "总长" --type design --limit 5
```

`publish` 在写入后完成登记与索引，返回外部知识 `id` 和固定 `version`，供后续 `knowledge_refs`
使用；它不会把产品变成公共 Skill，也不会替代原 Study。未来 Assessment 反馈仍
走现有中央 experience 机制。

## 资产一致性、陈旧来源与拒绝条件

`check-assets` 检查固定基线引用的文件是否存在及哈希是否一致，返回 `ok` 和逐文件结果。
`use` 会执行相同检查；文件缺失或被改动时拒绝引用，包括旧声明仍引用的历史源文件。
`resume` 是轻量摘要，`publish` 保存既有记录供检索，这两项不会每次读取全部大型附件。

用同一资产 ID 登记新版时，旧声明的来源保持固定；`resume` 的 `stale_sources` 会列出
受影响的声明。`use` 返回实体的 payload 和 `publish` 的 JSON 快照中也保存
`stale_source_statements`。这表示相关声明在重新用于工程判断前
必须由 Codex 解释并重新确认；不能把陈旧声明静默当作当前事实。`check-assets` 的
通过也仅证明文件完整性，不代表 OCR、CAD 解析、求解验证或产品验收通过。

## 接管边界

二维图纸可以形成有用的部分接管，但不能单独证明未显示的三维特征历史、制造意图、
未标出的公差、材料牌号、网格、边界条件或工程验收。产品约束与个人/团队偏好应
分开记录；偏好不是物理证据。不得伪造过去的 CAD/CAE 实验、结果或批准状态。

原生装配工程应连同依赖文件保留，可将完整项目包作为附件登记；附件复制不会重写
CAD 文件内部的引用路径。后续执行应在工作副本中解析这些依赖，原始附件继续保持固定。
