<!-- eds-knowledge: {"id":"method-fluid-gap","version":"1","type":"method","title":"平行板狭缝层流压降 / Laminar gap pressure drop","date":"2026-11-02","attribution":"synthetic_fixture","domain":"cae","project":"eds-demo","tags":["synthetic","层流","压力","pressure"],"problem":"狭缝间距改变时的压力损失","method":"充分发展层流解析表达","assumptions":["steady","incompressible","Newtonian","no slip","wide plates"],"sources":[{"uri":"synthetic-source.md","locator":"§ A: problem and assumptions"},{"uri":"synthetic-source.md","locator":"§ B: equations and units"},{"uri":"synthetic-source.md","locator":"§ E: transfer limits"}],"conditions":{"unit_system":"SI","h_definition":"full plate gap in m","velocity_control":"fixed mean U","flow":"laminar independently justified"},"relations":[{"type":"tested_by","id":"experiment-gap-sweep","version":"1"}]} -->

# 平行板狭缝层流压降方法（合成知识样例）

本单元只演示提取和检索；来源是可读取的仓库合成资料，不是真实论文或已验证工程经验。

## 问题与表达

固定平均流速 U 时比较间距 h 对压力损失的影响。由充分发展、不可压、稳态牛顿流体动量方程及两壁无滑移条件，可得到：

`Delta_p = 12 * mu * L * U / h^2`

Delta_p 是压差（Pa）；mu 是动力黏度（Pa s）；L 是发展段长度（m）；U 是平均流速（m/s）；h 是两板完整间距（m）。
这些定义与公式是同一知识单元的必要条件，不能只引用一个数值。推导来源为 synthetic-source.md § B。

`Re_h = rho * U * h / mu` 是间距定义的无量纲雷诺数，rho 的单位为 kg/m3。
本例不以某个雷诺数阈值证明层流，也不把 Re_h 与水力直径定义混用。

## 适用范围与限制

宽度远大于间距；忽略入口和侧壁效应；层流需有独立适用依据。固定体积流量、湍流、可压缩或强入口效应时应重新判断表达。
反馈单元只是合成文本，不构成物理验证。与实际任务的来源、工况和模型表达差异必须由 Codex 判断。
