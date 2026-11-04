# README 演示图片说明

图片选自 2026-11-03/04 的实机验证成果。README 直接嵌入结果图片，说明放在附近正文中：CAD 图宽 360 px，三张温度云图各宽 240 px、并排展示；四张 PNG 合计约 408 KiB。

## 展示内容

| 展示图 | 实际来源与含义 |
| --- | --- |
| [CAD 三孔零件](images/demos/cad-three-hole.png) | SolidWorks 独立 CAD 测试中的候选 B，展示原生几何及等轴预览。对应 `B-resume-final-recovered_isometric.bmp`，MCP artifact 为 `mcp-e7868419d0714f6c89564e825b3e80f5-1`。 |
| [10 mm / 5 W](images/demos/thermal-10mm-5w.png) | 联合任务基线，细网格 M2 的最高温度为 336.7907964229 K，即 63.6408℃，未满足 60℃ 判据。 |
| [14 mm / 5 W](images/demos/thermal-14mm-5w.png) | 温度反馈推动厚度修订，细网格 M2 的最高温度为 331.2792515548 K，即 58.1293℃，满足相同判据。 |
| [14 mm / 4 W](images/demos/thermal-14mm-4w.png) | 只改变功率，复用实际几何、对应关系和网格，最高温度为 324.8271710087 K，即 51.6772℃。 |

三孔候选 B 与热分析矩形实体属于不同测试。CAD 图片展示候选的实际建模效果，不表示 B 是最终选定方案；CAD 独立比较在规定几何判据下选择的是 A，详见 [CAD 修复与复验](live-cad-repair-validation.md)。

热分析几何为长 120 mm、宽 20 mm 的矩形实体，厚度为 10 mm 或 14 mm。输入端施加总功率 5 W / 4 W，其余五面与 25℃ 环境对流、辐射换热；导热率 167 W/(m·K)，换热系数 15 W/(m²·K)，发射率 0.8。CAE 按实际 CAD 平面和尺寸重建实体，本例未验证 STEP 几何传递。

厚度比较完成了两网格与热平衡检查；4 W 工况沿用 6880 个四面体、13447 个自由度，仅做一次新求解。条件、过程偏差和结果见 [联合验收记录](live-coupled-validation.md)。这些结果用于验证规定输入下的工作流程，不是产品实测校准或制造放行结论。

## 图像与结果的对应

- CAD 原图是实际导出的 BMP；发布时仅无损转换为 PNG，保持原有像素、构图和颜色。
- 三张 COMSOL 温度图为实际解的导出 PNG，发布副本与留存成果的 SHA-256 一致。它们是 MCP 工作流导出的求解图，不表示 COMSOL Desktop 界面同步。
- 数值来自对应工况的实际结果记录，并非从图上估读。各图采用独立的自动色标，颜色不能直接跨图比较。
- 原始模型、完整 MCP 响应及成果清单继续保存在本地工作区，公开仓库只收录上述精选展示副本。

<details>
<summary>发布图片的 SHA-256</summary>

| 文件 | SHA-256 |
| --- | --- |
| `cad-three-hole.png` | `9d6b6a5eac4e413e91c4e48f08d9a071a498a8a38566835c89a99fee38965a0e` |
| `thermal-10mm-5w.png` | `293c036ef04d6e33ffa03b28245c1c077540e78d8639510e61632105357792f4` |
| `thermal-14mm-5w.png` | `dc65b31118c7ae8e4fdfd1d314fe0003527249c4f68a1f3e1c62dc67ef89312d` |
| `thermal-14mm-4w.png` | `faf5b1a4d703b3cbb339f77905b7a5c9d336a1a7c2dadd16e3a189e2ba91d3cd` |

CAD 原 BMP 的 SHA-256 为 `c713412f64e78fdac76a3fc0683ff48a6a509e5f5887a88c7c0b46581a6fdc0b`。

</details>
