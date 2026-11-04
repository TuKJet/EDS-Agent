<!-- eds-knowledge: {"id":"experiment-gap-sweep","version":"1","type":"experiment","title":"间距扫描与压力对照 / Gap sweep experiment","date":"2026-11-02","attribution":"synthetic_fixture","domain":"cae","project":"eds-demo","sources":[{"uri":"synthetic-source.md","locator":"§ C: experiment design table"},{"uri":"synthetic-source.md","locator":"§ B: reference relation and units"}],"conditions":{"gap_mm":[0.5,1.0,2.0],"fixed":["rho","mu","mean U","L"],"unit_conversion":"h in mm multiplied by 0.001 before SI evaluation"},"relations":[{"type":"uses","id":"method-fluid-gap","version":"1"},{"type":"feedback","id":"feedback-gap-laminar","version":"1"}]} -->

# 间距扫描实验方案（未执行的合成样例）

问题：充分发展层流简化与包含入口效应的表达在当前用途下是否能区分？
变量：h = 0.5、1.0、2.0 mm；固定 rho、mu、平均 U 和 L。将 h 转为 m 后计算。
对照：使用方法单元给出的压降公式，只作为理想化问题的数值参考。
观察：压力损失 pressure drop、质量守恒、残差历史、实际载荷边界及单位。
判据：将候选之间差异与各自的网格细化误差分开，差异不可区分时保留候选并说明需要的下一项观察。

这是实验设计夹具，没有提交任务；不能据此生成 completed Run 或真实模型验证声明。
