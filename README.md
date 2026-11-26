# Open Mining Skills · 矿山三维 AI Skills

> 面向矿山三维建模与数字孪生的开源 Agent Skills 集合，兼容 Codex / OpenCode / Claude Code。

Open Mining Skills 把矿山三维场景建设中的专业知识、数据处理流程和质量检查规则，封装成 AI 编程代理可直接调用的 Skills。每个 Skill 由 `SKILL.md` 执行规范、可执行的 Python 工具和参考资料组成，目标是把 DWG/DXF、导线点 XYZ、等高线、点云等原始数据，稳定地转换为可在 Cesium 中加载的矿山三维场景，并进一步接入人员、设备、监测与实时业务数据。

## 覆盖范围

- **数据解析**：DWG / DXF、导线点 XYZ、Contour 等高线、LAS / LAZ 点云
- **空间处理**：矿山坐标系识别、坐标转换、模型配准与误差评估
- **三维建模**：TIN / DEM 地形、地质体建模、Mesh 优化、GLB / glTF 导出
- **Web 可视化**：3D Tiles 转换、CesiumJS 场景搭建与交互
- **数字孪生**：人员定位、安全监测、工程机械、三维实体绑定、WebSocket 实时数据

## 兼容性

- Codex：`.agents/skills/`
- OpenCode：`.agents/skills/` 或 `.opencode/skills/`
- Claude Code：`.claude/skills/`

## License

MIT
