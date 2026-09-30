# 部署手册（Ubuntu / Debian）

目标：将个人主页部署到云服务器 `146.56.223.180`，通过 `https://yjgnet.cn` 访问。

架构：`浏览器 → nginx (80/443) → uvicorn (127.0.0.1:8000) → FastAPI`

## 0. 前置检查

在服务器上确认：

```bash
# 系统版本（应为 Ubuntu / Debian）
lsb_release -a

# 确认 80/443 未被其他服务占用
sudo ss -tlnp | grep -E ':80|:443'

# 确认域名解析已指向服务器（本地执行）
ping yjgnet.cn
```

同时确认腾讯云控制台安全组已放行 **80、443** 端口。

## 1. 安装基础依赖

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx ufw
```

## 2. 创建专用系统用户与目录

```bash
sudo useradd --system --shell /usr/sbin/nologin --home-dir /opt/homepage homepage
sudo mkdir -p /opt/homepage
sudo chown homepage:homepage /opt/homepage
```

## 3. 上传项目代码

在本地项目根目录执行打包（Windows 下用 tar 或直接 scp 整个目录）：

```bash
# 方式一：rsync 增量同步（推荐，需本地有 WSL/Git Bash）
rsync -avz --exclude '__pycache__' --exclude '.venv' --exclude '.env' \
  ./ root@146.56.223.180:/opt/homepage/

# 方式二：scp
scp -r app content templates static requirements.txt root@146.56.223.180:/opt/homepage/
```

上传后修正属主：

```bash
sudo chown -R homepage:homepage /opt/homepage
```

## 4. 服务器安装 Miniconda 并创建同名 conda 环境

```bash
# 下载安装 Miniconda（清华镜像）
wget https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh
sudo bash /tmp/miniconda.sh -b -p /opt/miniconda3

# 配置清华 conda 镜像源
# （新版 conda 25+ 要求接受官方源 ToS 才能建环境，配置镜像源可一并规避并加速）
sudo tee /opt/miniconda3/.condarc > /dev/null << 'EOF'
channels:
  - defaults
default_channels:
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main
  - https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/r
custom_channels:
  conda-forge: https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud
  pytorch: https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud
show_channel_urls: true
EOF

# 创建与本地同名的环境
sudo /opt/miniconda3/bin/conda create -n homepage python=3.12 -y

# 安装项目依赖（清华镜像加速，注意先完成第 3 步上传代码）
sudo /opt/miniconda3/envs/homepage/bin/pip install -r /opt/homepage/requirements.txt \
  -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> 提示：若跳过镜像源配置直接建环境报 `CondaToSNonInteractiveError`，
> 也可执行 `conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main` 等命令接受条款。

## 5. 配置环境变量

```bash
sudo cp /opt/homepage/.env.example /opt/homepage/.env
sudo nano /opt/homepage/.env   # 按需修改（LLM Key 可以先留空）
sudo chown homepage:homepage /opt/homepage/.env
sudo chmod 600 /opt/homepage/.env
```

## 6. 配置 systemd 服务

```bash
sudo cp /opt/homepage/deploy/homepage.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now homepage

# 验证服务状态
sudo systemctl status homepage
curl -s http://127.0.0.1:8000/api/health   # 应返回 {"status":"ok"}
```

## 7. 配置 nginx

```bash
sudo cp /opt/homepage/deploy/nginx.yjgnet.cn.conf /etc/nginx/sites-available/yjgnet.cn
sudo ln -s /etc/nginx/sites-available/yjgnet.cn /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

# 此时用 IP 访问应已能看到网站
curl -I http://146.56.223.180
```

## 8. 签发 HTTPS 证书

```bash
sudo certbot --nginx -d yjgnet.cn -d www.yjgnet.cn
# 按提示输入邮箱、同意条款，选择自动重定向 http -> https（redirect）
```

certbot 会自动修改 nginx 配置并添加自动续期任务，验证：

```bash
sudo certbot renew --dry-run
curl -I https://yjgnet.cn
```

> 常见问题：若 `http://yjgnet.cn` 正常但 `https://` 连接超时，而服务器上
> `curl -k https://127.0.0.1/` 返回 200，说明 nginx 与证书均正常，
> 是云安全组未放行 **443**（腾讯云控制台 → 安全组 → 入站规则 → 放行 TCP:443）。
> 证书续期由 certbot 定时器（`systemctl list-timers | grep certbot`）自动完成，无需手工维护。

## 9. 防火墙

```bash
sudo ufw allow 'Nginx Full'
sudo ufw allow OpenSSH
sudo ufw enable
sudo ufw status
```

（若 ufw 未启用则可跳过；注意务必保留 SSH 端口，避免把自己关在外面。）

## 10. 上线验收清单

- [ ] `https://yjgnet.cn` 正常打开，证书有效（浏览器无警告）
- [ ] `http://yjgnet.cn` 自动跳转 https
- [ ] `https://www.yjgnet.cn` 正常访问
- [ ] 主页滚动动画、导航高亮正常
- [ ] `/blog` 列表与文章详情、代码高亮正常
- [ ] AI 助手对话返回流式回复
- [ ] 简历 PDF 可下载
- [ ] 手机浏览器访问布局正常

## 日常运维

### 快速同步（推荐，代替手工 scp）

本地改完内容或代码后，在项目根目录执行 `sync.py` 一键同步（需 `pip install paramiko`，
服务器连接信息在 `deploy/.sync_config.json`，该文件已被 .gitignore 排除不会提交）：

```bat
call conda activate homepage
python sync.py content    rem 只同步文章/文案（site.yml、posts），无需重启，秒级生效
python sync.py static     rem 同步图片/简历等静态资源，无需重启
python sync.py app        rem 同步后端代码，自动重启服务
python sync.py templates  rem 同步页面模板，自动重启服务
python sync.py all        rem 全量同步全部内容
```

### 更新网站内容（手工方式）

```bash
# 本地修改 content/site.yml 或 content/posts/*.md 后上传
scp content/site.yml root@146.56.223.180:/opt/homepage/content/
# 内容带自动重载，无需重启服务，刷新页面即可看到
```

### 更新代码

```bash
# 上传改动的文件后重启服务
sudo systemctl restart homepage
```

### 查看日志

```bash
sudo journalctl -u homepage -f --no-pager   # 应用日志
sudo tail -f /var/log/nginx/access.log      # 访问日志
```

### 接入真实 LLM（可选）

在服务器上编辑 `/opt/homepage/.env`，填入：

```
LLM_API_KEY=sk-xxxx
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

然后 `sudo systemctl restart homepage`，AI 助手即切换为真实模型，前端无需改动。

## 回滚步骤

如果新版本上线后异常：

```bash
# 方案一：重启服务
sudo systemctl restart homepage

# 方案二：回退代码（若服务器上有备份）
sudo mv /opt/homepage /opt/homepage.bak
sudo mv /opt/homepage.previous /opt/homepage

# 方案三：改回 nginx 旧配置
sudo cp /etc/nginx/sites-available/yjgnet.cn.bak /etc/nginx/sites-available/yjgnet.cn
sudo nginx -t && sudo systemctl reload nginx
```

建议每次上线前先备份：

```bash
sudo cp -r /opt/homepage /opt/homepage.previous
```
