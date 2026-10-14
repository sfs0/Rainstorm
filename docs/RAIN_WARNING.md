# 暴雨预警第一版

入口：`http://8.130.160.137/#/home/analyse?tool=rainstorm`，使用现有网页账号登录。第四个“暴雨预警”标签支持上传 CSV、下载示例、使用示例试跑、自动识别流域及校验、提交异步任务、显示计算进度和结果。

中央区域显示最高风险、河段风险、24/48 小时降水、区域协同性、重点站点，以及综合、公众、交通、水利、应急建议。左侧记录保存在当前浏览器；任务结果保存在服务器 SQLite 中。刷新可恢复最近结果，重新选择文件后才可再次提交；上传原始文件不落盘。

## 方法与输入

第一版移植论文目录中 `03_analyze_and_plot_innov.py` 与 `basin_station_catalog_innov.py` 的当前规则和权重。按站点计算滚动降水与辅助要素，生成风险指数及河段汇总。不是调用旧的、数值不一致的历史结果文件。

必需字段：`Station_Id_C`、`datetime`（或 `Year/Mon/Day/Hour`）、`PRE_3h`、`PRS`、`VIS`、`WIN_S_MAX`、`WEP_Now`。支持 UTF-8/BOM 与 GBK，每文件不超过 10 MB、100000 条数据；每站至少 16 个连续 3 小时时次，各站截至时间一致。重复时次、缺时次、无效数字、缺失降水会明确拒绝。辅助要素缺失会说明影响。

支持长江、黄河。优先核对 CSV 的 `basin` 与站点目录；未提供流域时以站号推断，必须能唯一识别。一个文件包含混合流域、未知流域或识别歧义时明确提示补充 CSV。没有额外流域选择框。未列入目录的站点需要提供流域、河段和站名。

示例来自已有历史观测：万州、宜昌、南京共 72 条，2026-03-13 至 2026-03-16，上、中、下游最高风险指数分别为 22.5、22.17、9.33，均为低风险。示例供格式和流程试用，日期不是当前日期。

当前建议由观测证据和规则生成，页面明确标记“基于观测证据的规则建议”。尚未接入 Qwen；没有配置或传输模型密钥，也没有外部模型请求。风险等级是本方法的观测风险分级，不是气象部门发布的官方预警信号。

## 结构与部署

- `frontend/dist/` 和基线恢复包原封保留。`frontend/extensions/` 是新增 Vue 组件和样式。
- 原 Vue 源码未找到，`scripts/build_web.py` 对已知编译产物做严格匹配的接入，输出 `build/web/dist`。主入口和所有 JS 依赖均带版本名，防止新旧缓存混用。基线改变后需要重新审查接入点。
- Python 标准库服务在 `127.0.0.1:8096` 运行，代码 `/opt/rainstorm-warning`，数据 `/var/lib/rainstorm-warning/jobs.sqlite`，服务名 `rainstorm-warning`，以 nginx 用户运行。
- Nginx 新增 `/rain-warning-api/` 代理；原 `/api/` 和 Java 服务保持原路由。服务和 Nginx 已启用开机启动。
- 接口：`GET /health`、`POST /validate`、`POST /jobs`、`GET /jobs/<id>`。POST 是 CSV 原始字节，文件名在 URL 编码的 `X-File-Name` 请求头。任务 ID 为随机 UUID，无公开任务列表。
- 此版沿用网页登录，新增 API 本身没有独立的账号授权；适用于目前试用。多用户正式使用前需将任务访问与已有登录权限关联，并制定结果保留与清理周期。

```bash
python scripts/build_web.py
python -m unittest discover -s warning-service/tests -v
python scripts/verify_snapshot.py
python scripts/deploy_warning.py
python scripts/smoke_warning.py --url http://8.130.160.137
```

部署脚本从标准输入读 SSH 密码，不保存密码；需要本地 paramiko。每次切换都保留当时网页和单个 Nginx 配置，路径记录于 `build/deployment-record.json`。当前线上构建 `c63915ed3194`，切换前备份 `/data/web/releases/before-warning-20261014T150001Z`。基线回退见 [ROLLBACK.md](ROLLBACK.md)；回退后如需停用新增服务，可执行 `systemctl disable --now rainstorm-warning`。

## 验证范围

15 项输入与评分测试通过，长江和黄河原始历史数据的河段最大评分与原方法对照一致。公网验证逐文件 SHA-256、示例下载、CSV 校验、异步任务完成、分类建议、无效 CSV 拒绝。本地使用相同编译页面验证四个标签、示例试跑、结果展示、建议切换和刷新恢复。真实站点第四个标签由用户确认可见。

本地浏览器测试 `scripts/preview_web.py` 只模拟本地页面登录与旧 API 的空记录，新的预警请求转发给本地预警服务；不部署到服务器、不读取或复制线上登录状态。浏览器扩展未开启本地文件访问权限，未自动验证从操作系统文件选择器上传；示例试跑经过同一个文件校验与分析处理链路。未重新运行原三个图像模型的业务推理。
