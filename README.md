# NYC Urban Environment

纽约城市环境宜居度交互可视化：按 ZIP Code 聚合空气质量、噪音与绿化指标，叠加公共设施图层，辅助选区对比。
github pages
https://zolaxiang-11.github.io/nyc_finalwork/

## 项目简介

组内其他同学已覆盖人口、教育、安全、地铁等主题。本模块聚焦**环境健康与日常便利**，回答：

1. 哪些 ZIP 区域环境更宜居？
2. 短板主要来自空气、噪音还是绿化？
3. 降温点、公厕、饮水点等公共设施覆盖是否充足？

前端以 Leaflet 着色地图 + D3 雷达图为主视图，支持阈值过滤、场景预设、设施图层开关与选区锁定对比。

## 主要功能

- **ZIP 着色地图**：按综合环境分 `environment_score` 着色，悬停查看细项分数
- **分数阈值过滤**：只保留综合分不低于设定底线的区域
- **维度筛选**：空气 / 安静 / 绿化附加条件
- **场景预设**：平衡、需要安静、日常便利
- **公共设施图层**：降温中心、公厕、饮水点，可调透明度
- **选区锁定 + 雷达图**：单击 ZIP 锁定，右侧对比空气、噪音、绿化
- **数据速览**：全市均值、Top / Bottom ZIP 摘要

## 指标体系

细项分数统一映射到 **0–100（越高越好）**：

| 指标 | 含义 | 数据来源 |
| --- | --- | --- |
| `air_quality_score` | 空气质量，污染越低分越高 | NYC Air Quality |
| `noise_score` | 安静程度，噪音投诉越少分越高 | NYC 311 |
| `green_score` | 绿荫水平 | NYC Tree Census |
| `environment_score` | 综合环境分 | 加权合成 |
| `facility_score` | 公共设施覆盖 | 降温点 / 公厕 / 饮水点 / 公园数量 |

综合环境分：

```text
environment_score = 0.45 * air + 0.35 * noise + 0.20 * green
```

设施分由 ZIP 内设施点位数量 min-max 归一化后取均值。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 数据处理 | Python、Pandas、NumPy |
| 前端 | HTML / CSS / JavaScript |
| 地图与可视化 | Leaflet、D3.js |
| 空间数据 | GeoJSON（NYC ZIP 边界） |

## 项目结构

```text
nyc-urban-environment/
├── data_pipeline/                 # 数据加工脚本
│   ├── build_environment_data.py  # 空气 / 噪音 / 绿化 → ZIP 环境分
│   ├── build_facilities_by_zip.py # 公共设施点位聚合到 ZIP
│   └── build_score4.py            # 环境分 + 设施分 → score4.csv
├── frontend/                      # 开发用前端
│   ├── index.html
│   ├── main.js
│   ├── styles.css
│   └── submission.html            # 说明文档页
├── docs/                          # 可直接部署的静态站点
├── output/                        # 加工后的 JSON / CSV
└── 执行方案.md
```

## 快速开始

### 1. 查看可视化

无需后端。用本地静态服务打开前端即可：

```bash
cd frontend
python -m http.server 8080
```

浏览器访问 `http://localhost:8080`。

若使用 `docs/` 作为 GitHub Pages 根目录，打开 `docs/index.html` 即可。

### 2. 重新生成数据（可选）

准备空气质量、311、树木普查及设施原始 CSV 后：

```bash
python data_pipeline/build_environment_data.py
python data_pipeline/build_facilities_by_zip.py
python data_pipeline/build_score4.py
```

产物：

- `output/environment_by_zip.csv`
- `output/facilities_by_zip.csv`
- `output/final_data.environment.json`
- `output/score4.csv`

## 数据来源

全部来自 NYC Open Data（免费公开）：

- Air Quality
- NYC 311（噪音相关诉求）
- Tree Census
- Heat Vulnerability Index
- Cooling Sites、Parks Drinking Fountains、Public Restrooms、Parks Properties

口径说明与局限见 `执行方案.md` 和 `frontend/submission.html`。

## 设计说明

- ZIP 为统一空间主键，设施点通过点落面映射到 ZIP
- 距离类可达性目前用设施数量近似，文档中说明了可升级为路网路由
- 不重复组员已完成的人口 / 教育 / 犯罪 / 地铁主题
