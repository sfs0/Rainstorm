# 暴雨预警第一版

入口：`http://8.130.160.137/#/home/analyse?tool=rainstorm`，使用现有网页账号登录。第四个“暴雨预警”标签支持上传 CSV、下载示例、使用示例试跑、自动识别流域及校验、提交异步任务、显示计算进度和结果。

中央区域显示最高风险、河段风险、24/48 小时降水、区域协同性、重点站点，以及综合、公众、交通、水利、应急建议。左侧记录保存在当前浏览器；任务结果保存在服务器 SQLite 中。刷新可恢复最近结果，重新选择文件后才可再次提交；上传原始文件不落盘。

## 方法与输入

第一版移植论文目录中 `03_analyze_and_plot_innov.py` 与 `basin_station_catalog_innov.py` 的当前规则和权重。按站点计算滚动降水与辅助要素，生成风险指数及河段汇总。不是调用旧的、数值不一致的历史结果文件。

必需字段：`Station_Id_C`、`datetime`（或 `Year/Mon/Day/Hour`）、`PRE_3h`、`PRS`、`VIS`、`WIN_S_MAX`、`WEP_Now`。支持 UTF-8/BOM 与 GBK，每文件不超过 10 MB、100000 条数据；每站至少 16 个连续 3 小时时次，各站截至时间一致。重复时次、缺时次、无效数字、缺失降水会明确拒绝。辅助要素缺失会说明影响。

支持长江、黄河。优先核对 CSV 的 `basin` 与站点目录；未提供流域时以站号推断，必须能唯一识别。一个文件包含混合流域、未知流域或识别歧义时明确提示补充 CSV。没有额外流域选择框。未列入目录的站点需要提供流域、河段和站名。

示例来自已有历史观测：万州、宜昌、南京共 72 条，2026-03-13 至 2026-03-16，上、中、下游最高风险指数分别为 22.5、22.17、9.33，均为低风险。示例供格式和流程试用，日期不是当前日期。

分类建议已接入 `qwen-max`，模型接收结构化观测证据，生成公众、交通、水利、应急建议；程序计算的数字、等级、综合证据和不确定性说明继续保留。风险等级是本方法的观测风险分级，不是气象部门发布的官方预警信号。模型输出接受 JSON 结构、数字/量值、目录站名、其他流域及明确预报/官方预警表述检查；不代表完全的事实核查或人工审核。格式或约束不通过时重写一次，再失败回退规则。未配置密钥、鉴权失败、限流或网络异常时也回退规则，页面显示原因，不输出上游响应正文或密钥。

## 配置 qwen-max

在服务器 `8.130.160.137` 以 root 编辑 `/etc/rainstorm-warning.env`（已建立，权限 root:root 600）：

```ini
DASHSCOPE_API_KEY=在这里填写真实百炼密钥
QWEN_MODEL=qwen-max
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

默认使用北京地域；密钥必须来自相同地域。其他地域或业务空间专属域名可以按照 [百炼官方兼容接口说明](https://www.alibabacloud.com/help/zh/model-studio/compatibility-of-openai-with-dashscope) 修改 BASE_URL。实际密钥不放入 Git、网页、截图或聊天；仓库只提供空白模板 `deployment/rainstorm-warning.env.example`。

填写后执行：

```bash
systemctl restart rainstorm-warning
systemctl is-active rainstorm-warning
curl -s http://127.0.0.1:8096/health
```

健康接口 `model_configured:true` 只表示服务读到非空密钥，不表示阿里云鉴权或模型权限已验证。然后网页重新点击“使用示例试跑”或提交新任务。成功时标记 `qwen-max · 大模型建议`，失败显示规则回退原因。旧任务保存原结果，不自动重新调用模型。

systemd 通过 `EnvironmentFile` 读取密钥，服务仍以 nginx 用户运行。模板只在文件不存在时创建，后续部署不覆盖已填密钥。模型接口为 HTTPS，禁止 HTTP 重定向，限制为百炼域名，防止配置错误时向其他域名发送凭据。

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

部署脚本从标准输入读 SSH 密码，不保存密码；需要本地 paramiko。每次切换都保留当时网页、单个 Nginx 配置，以及已有预警 Python 文件与服务单元，路径记录于 `build/deployment-record.json`。当前前端构建 `26baec3a9645`。实际密钥文件不复制到备份中。基线回退见 [ROLLBACK.md](ROLLBACK.md)；回退后如需停用新增服务，可执行 `systemctl disable --now rainstorm-warning`。

## 验证范围

15 项输入与评分测试通过，长江和黄河原始历史数据的河段最大评分与原方法对照一致。公网验证逐文件 SHA-256、示例下载、CSV 校验、异步任务完成、分类建议、无效 CSV 拒绝。本地使用相同编译页面验证四个标签、示例试跑、结果展示、建议切换和刷新恢复。真实站点第四个标签由用户确认可见。

Qwen 接入新增 8 项测试，覆盖请求的模型和鉴权头、无密钥回退、成功生成并保持分数、重写与回退、不合法证据拒绝、鉴权错误脱敏、域名与重定向限制，共 23 项通过。测试使用模拟响应，真实 Qwen 调用需管理员填写有效密钥后验证；部署时不代填密钥、不产生模型调用费用。

本地浏览器测试 `scripts/preview_web.py` 只模拟本地页面登录与旧 API 的空记录，新的预警请求转发给本地预警服务；不部署到服务器、不读取或复制线上登录状态。浏览器扩展未开启本地文件访问权限，未自动验证从操作系统文件选择器上传；示例试跑经过同一个文件校验与分析处理链路。未重新运行原三个图像模型的业务推理。
