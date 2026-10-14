# 当前网页的恢复说明

固定回退点：`server-baseline-20261014`。

本说明只恢复 `8.130.160.137` 的 `/data/web/dist` 和 `/etc/nginx/conf.d/web.conf`。不恢复 Java 后端、管理端、数据库或全局 Nginx 配置。上传、分析等业务仍依赖原有后端服务。

## 1. 获取并核对备份

在有 Git 的本地电脑检出固定标签：

```bash
git clone --branch server-baseline-20261014 https://github.com/sfs0/Rainstorm.git
cd Rainstorm
python scripts/verify_snapshot.py
```

也可以从 GitHub 的标签页面下载 ZIP。服务器当前没有安装 Git，无须为了恢复而在服务器安装 Git。

## 2. 传输到服务器

从本地仓库目录执行，SSH 密码交互输入，不写入命令或文件：

```bash
scp snapshots/web-8.130.160.137-20261014-before-rain-warning.tar.gz scripts/restore-web.sh root@8.130.160.137:/tmp/
ssh root@8.130.160.137
```

## 3. 校验后恢复

在目标服务器执行：

```bash
bash /tmp/restore-web.sh /tmp/web-8.130.160.137-20261014-before-rain-warning.tar.gz
bash /tmp/restore-web.sh /tmp/web-8.130.160.137-20261014-before-rain-warning.tar.gz --apply
```

第一条只校验压缩包。第二条才恢复文件：保留恢复前的前端和路由，替换为基线，执行 `nginx -t`，通过后重载或启动 Nginx。如果配置校验或服务操作失败，会尝试恢复原网页和配置。恢复前的文件保留在脚本输出的 `/var/backups/rainstorm/` 目录中。

## 4. 检查访问

```bash
curl -I http://127.0.0.1/
curl -I http://127.0.0.1/home/analyse
curl -I http://127.0.0.1/assets/index-Me4TUIQZ.js
```

随后从外网打开 `http://8.130.160.137/#/home/analyse`，确认页面和原有功能。不要只以首页 HTTP 200 判定业务计算已恢复。

## 校验与已知边界

- 捕获时逐文件核对了服务器上的 SHA-256，原始恢复包同时保留权限。
- 本地完整性脚本和恢复脚本校验模式已执行；恢复脚本没有在现有线上部署执行，未做真实线上切换演练。
- 前端是 Vue/Vite 编译产物，尚无对应的 Vue 开发源码。
- 本次网页备份不包含 SSH 密码、数据库凭据或 API 密钥；未读取完整后端敏感配置。
- 后端完整快照受自动审批限制，未包含在当前提交中。
