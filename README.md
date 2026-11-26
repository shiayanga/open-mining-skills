# Open Mining Skills · 矿山三维 AI Skills

> 面向矿山三维建模与数字孪生的开源 Agent Skills 集合，技能目录直接位于仓库根目录。

Open Mining Skills 把矿山三维场景建设中的专业知识、数据处理流程和质量检查规则，封装成 AI 编程代理可直接调用的 Skills。每个 Skill 由 `SKILL.md` 执行规范、可执行的 Python 工具和参考资料组成，目标是把 DWG/DXF、导线点 XYZ、等高线、点云等原始数据，稳定地转换为可在 Cesium 中加载的矿山三维场景，并进一步接入人员、设备、监测与实时业务数据。

## 覆盖范围

- **数据解析**：DWG / DXF、导线点 XYZ、Contour 等高线、LAS / LAZ 点云
- **空间处理**：矿山坐标系识别、坐标转换、模型配准与误差评估
- **三维建模**：TIN / DEM 地形、地质体建模、Mesh 优化、GLB / glTF 导出
- **Web 可视化**：3D Tiles 转换、CesiumJS 场景搭建与交互
- **数字孪生**：人员定位、安全监测、工程机械、三维实体绑定、WebSocket 实时数据

## 首批 Skills（骨架）

首批聚焦「数据接入 → 坐标配准 → 地形建模 → 三维建模 → 切片发布 → 场景展示 → 质量检查」核心链路，共 8 个技能。除 `README.md` 与 `LICENSE` 外，每个顶层目录都是一个独立技能：

| Skill | 职责 | 状态 |
|---|---|---|
| [mine-data-inspection](mine-data-inspection/SKILL.md) | 原始数据识别、范围统计与质量报告 | 骨架 |
| [mine-cad-parser](mine-cad-parser/SKILL.md) | DWG/DXF 解析、图层与三维实体提取 | 骨架 |
| [mine-coordinate-registration](mine-coordinate-registration/SKILL.md) | 坐标系识别、转换、控制点配准与 RMSE 评估 | 骨架 |
| [mine-terrain-modeling](mine-terrain-modeling/SKILL.md) | 等高线/导线点约束 TIN 与 DEM 地形重建 | 骨架 |
| [mine-3d-modeling](mine-3d-modeling/SKILL.md) | TIN/DEM 转 Mesh、道路/建筑/采坑/边坡建模与 GLB 导出 | 骨架 |
| [mine-3d-tiles](mine-3d-tiles/SKILL.md) | GLB/点云切片、LOD 与 3D Tiles 发布 | 骨架 |
| [mine-cesium-visualization](mine-cesium-visualization/SKILL.md) | CesiumJS 场景、地形/3D Tiles/GLB 加载、图层与测量 | 骨架 |
| [mine-model-quality-check](mine-model-quality-check/SKILL.md) | 模型拓扑、几何、坐标与精度独立检查 | 骨架 |

每个技能目录包含 `SKILL.md` 执行规范，以及 `scripts/`（可执行工具）和 `references/`（技术资料）占位目录。后续批次将补充点云、地质建模、项目编排器及数字孪生业务技能。

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
