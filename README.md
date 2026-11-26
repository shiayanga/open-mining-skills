# Open Mining Skills · 矿山三维 AI Skills

> 面向矿山三维建模与数字孪生的开源 Agent Skills 集合，技能目录直接位于仓库根目录。

Open Mining Skills 把矿山三维场景建设中的专业知识、数据处理流程和质量检查规则，封装成 AI 编程代理可直接调用的 Skills。每个 Skill 由 `SKILL.md` 执行规范、可执行的 Python 工具和参考资料组成，目标是把 DWG/DXF、导线点 XYZ、等高线、点云等原始数据，稳定地转换为可在 Cesium 中加载的矿山三维场景，并进一步接入人员、设备、监测与实时业务数据。

## 覆盖范围

- **数据解析**：DWG / DXF、导线点 XYZ、Contour 等高线、LAS / LAZ 点云
- **空间处理**：矿山坐标系识别、坐标转换、模型配准与误差评估
- **三维建模**：TIN / DEM 地形、地质体建模、Mesh 优化、GLB / glTF 导出
- **Web 可视化**：3D Tiles 转换、CesiumJS 场景搭建与交互
- **数字孪生**：人员定位、安全监测、工程机械、三维实体绑定、WebSocket 实时数据

## 技能清单（骨架）

规划中的 17 个技能已全部建立骨架。除 `README.md` 与 `LICENSE` 外，每个顶层目录都是一个独立技能：

| 分类 | Skill | 职责 |
|---|---|---|
| 编排 | [mine-project-orchestrator](mine-project-orchestrator/SKILL.md) | 任务拆解、技能路由与交付契约检查 |
| 数据识别与解析 | [mine-data-inspection](mine-data-inspection/SKILL.md) | 原始数据识别、范围统计与质量报告 |
| 数据识别与解析 | [mine-cad-parser](mine-cad-parser/SKILL.md) | DWG/DXF 解析、图层与三维实体提取 |
| 空间计算 | [mine-coordinate-registration](mine-coordinate-registration/SKILL.md) | 坐标系识别、转换、控制点配准与 RMSE 评估 |
| 空间计算 | [mine-terrain-modeling](mine-terrain-modeling/SKILL.md) | 等高线/导线点约束 TIN 与 DEM 地形重建 |
| 空间计算 | [mine-point-cloud](mine-point-cloud/SKILL.md) | 点云去噪、地面分类、配准与地表重建 |
| 三维模型生成 | [mine-3d-modeling](mine-3d-modeling/SKILL.md) | TIN/DEM 转 Mesh、道路/建筑/采坑/边坡建模与 GLB 导出 |
| 三维模型生成 | [mine-geological-modeling](mine-geological-modeling/SKILL.md) | 地层、断层、矿体的隐式三维地质建模 |
| 三维模型生成 | [mine-3d-tiles](mine-3d-tiles/SKILL.md) | GLB/点云切片、LOD 与 3D Tiles 发布 |
| 场景展示与交互 | [mine-cesium-visualization](mine-cesium-visualization/SKILL.md) | CesiumJS 场景、地形/3D Tiles/GLB 加载、图层与测量 |
| 场景展示与交互 | [mine-scene-interaction](mine-scene-interaction/SKILL.md) | Cesium 拾取、选中、弹窗、高亮、轨迹与筛选 |
| 质量管理 | [mine-model-quality-check](mine-model-quality-check/SKILL.md) | 模型拓扑、几何、坐标与精度独立检查 |
| 数字孪生业务 | [mine-iot-integration](mine-iot-integration/SKILL.md) | 对接 Spring Boot / ThingLinks，统一设备 ID 与实时事件 |
| 数字孪生业务 | [mine-personnel-tracking](mine-personnel-tracking/SKILL.md) | 人员定位、轨迹回放、区域统计与电子围栏 |
| 数字孪生业务 | [mine-safety-monitoring](mine-safety-monitoring/SKILL.md) | 监测设备、动态指标、阈值判断与告警 |
| 数字孪生业务 | [mine-machinery-management](mine-machinery-management/SKILL.md) | 工程机械位置、姿态、状态、轨迹与动画联动 |
| 数字孪生业务 | [mine-3d-entity-binding](mine-3d-entity-binding/SKILL.md) | 业务实体 ↔ 场景对象 ↔ 模型节点的三层绑定 |

每个技能目录包含 `SKILL.md` 执行规范，以及 `scripts/`（可执行工具）和 `references/`（技术资料）目录。技能之间的依赖关系写在各文件末尾的 Related Skills 中。

实现进度：`mine-data-inspection` v0.1 已提供可执行脚本与测试（DXF / XYZ 巡检），其余技能仍为骨架。

## 使用方式

本仓库是纯 Skills 集合，不绑定任何单一工具的目录约定。使用时把需要的技能目录复制或软链接到对应工具的 skills 目录：

| 工具 | 技能发现目录 |
|---|---|
| Codex | `.agents/skills/` |
| OpenCode | `.agents/skills/` 或 `.opencode/skills/` |
| Claude Code | `.claude/skills/` |

例如，在目标项目根目录执行：

```bash
ln -s /path/to/open-mining-skills/mine-cad-parser .agents/skills/mine-cad-parser
```

## License

MIT
