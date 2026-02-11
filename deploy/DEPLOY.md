# VoiceGrow 部署文档

## 部署架构

```
┌──────────┐         ┌──────────────────────┐         ┌──────────────────────────┐
│  小爱音箱  │         │  外网 VPS              │         │  内网服务器                │
│          │  公网    │                      │  WG隧道  │                          │
│  play_url├────────►│  Nginx (:443)        ├────────►│  VoiceGrow Server (:8000)│
│  WebSocket│         │  ├ /audio/* → MinIO  │         │  ├ ASR (Whisper)         │
│          │         │  ├ /ws      → WS     │         │  ├ NLU                   │
│          │         │  └ /api/*   → HTTP   │         │  ├ TTS (edge-tts)        │
└──────────┘         │                      │         │  └ LLM                   │
                     │  音频缓存 (max 1GB)   │         │                          │
                     └──────────────────────┘         │  MinIO (:9000)           │
                                                      │  MySQL (:3306)           │
                                                      │  Redis (:6379)           │
                                                      └──────────────────────────┘
```

**设计原则**: 控制信令走 VPS 转发，音频数据由 Nginx 缓存加速。

## 前置条件

| 组件 | 内网服务器 | VPS |
|------|-----------|-----|
| OS | Linux (Ubuntu/Debian) | Linux (Ubuntu/Debian) |
| Python | 3.10+ | 不需要 |
| Docker | 推荐 (MySQL/MinIO/Redis) | 不需要 |
| Nginx | 不需要 | 必须 |
| WireGuard | 必须 | 必须 |
| 域名 + SSL | 不需要 | 必须 (Let's Encrypt) |

## 第一步：WireGuard 组网

### VPS 端 (`/etc/wireguard/wg0.conf`)

```ini
[Interface]
Address = 10.0.0.1/24
ListenPort = 51820
PrivateKey = <VPS_PRIVATE_KEY>

[Peer]
PublicKey = <内网服务器_PUBLIC_KEY>
AllowedIPs = 10.0.0.2/32
```

### 内网服务器端 (`/etc/wireguard/wg0.conf`)

```ini
[Interface]
Address = 10.0.0.2/24
PrivateKey = <内网服务器_PRIVATE_KEY>

[Peer]
PublicKey = <VPS_PUBLIC_KEY>
Endpoint = <VPS公网IP>:51820
AllowedIPs = 10.0.0.1/32
PersistentKeepalive = 25
```

### 启动

```bash
# 两端分别执行
sudo systemctl enable wg-quick@wg0
sudo systemctl start wg-quick@wg0

# 验证连通性
# VPS 上:
ping 10.0.0.2
# 内网服务器上:
ping 10.0.0.1
```

## 第二步：内网服务器部署

### 2.1 基础服务确认

VoiceGrow 依赖以下服务，使用现有实例即可，无需额外部署：

| 服务 | 默认端口 | 用途 |
|------|---------|------|
| MySQL 8.0 | 3306 | 内容元数据 |
| MinIO | 9000 | 音频文件存储 |
| Redis | 6379 | 缓存 / 会话 |

确认服务可用：

```bash
# MySQL
mysql -h <MYSQL_HOST> -u voicegrow -p -e "SELECT 1"

# MinIO
curl http://<MINIO_HOST>:9000/minio/health/live

# Redis
redis-cli -h <REDIS_HOST> ping
```

### 2.2 VoiceGrow Server

```bash
cd voice_grow/server

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp ../.env.example ../.env
```

编辑 `.env`，填入现有服务的实际地址：

```bash
# TTS 后端
TTS_BACKEND=edge-tts

# MySQL — 填写现有 MySQL 地址和凭据
MYSQL_HOST=<你的MySQL地址>
MYSQL_PORT=3306
MYSQL_USER=voicegrow
MYSQL_PASSWORD=<你的密码>
MYSQL_DATABASE=voicegrow

# Redis — 填写现有 Redis 地址
REDIS_HOST=<你的Redis地址>

# MinIO — 填写现有 MinIO 地址和凭据
MINIO_ENDPOINT=<你的MinIO地址>:9000
MINIO_ACCESS_KEY=<你的AccessKey>
MINIO_SECRET_KEY=<你的SecretKey>
MINIO_BUCKET=voicegrow

# 公网音频 URL — 替换为你的 VPS 域名
MINIO_PUBLIC_BASE_URL=https://your-domain.com/audio
```

```bash
# 启动服务
python -m app.main
```

启动后服务会自动：
- 创建 MinIO bucket (如不存在)
- 设置 bucket 公开读取策略 (Nginx 反代无需签名)

### 2.3 验证内网服务

```bash
# MinIO 可用
curl http://localhost:9000/minio/health/live

# VoiceGrow API 可用
curl http://localhost:8000/health

# WebSocket 端口监听
ss -tlnp | grep 4399
```

## 第三步：VPS Nginx 部署

### 3.1 安装 Nginx + SSL

```bash
sudo apt update && sudo apt install -y nginx certbot python3-certbot-nginx

# 获取 SSL 证书
sudo certbot --nginx -d your-domain.com
```

### 3.2 部署 Nginx 配置

```bash
# 复制配置文件
sudo cp deploy/nginx/voicegrow.conf /etc/nginx/sites-available/

# 替换占位符 (⚠️ 必须替换)
sudo sed -i 's/YOUR_DOMAIN/your-domain.com/g' /etc/nginx/sites-available/voicegrow.conf
sudo sed -i 's/10.0.0.2/<内网服务器WireGuard IP>/g' /etc/nginx/sites-available/voicegrow.conf

# 启用配置
sudo ln -sf /etc/nginx/sites-available/voicegrow.conf /etc/nginx/sites-enabled/

# 创建缓存目录
sudo mkdir -p /var/cache/nginx/voicegrow_audio

# 验证 + 重载
sudo nginx -t && sudo systemctl reload nginx
```

### 3.3 验证 VPS 转发

```bash
# 健康检查
curl https://your-domain.com/health

# API 转发
curl https://your-domain.com/api/health

# 音频转发 (需要先有内容)
# 上传测试文件到 MinIO 后:
curl -I https://your-domain.com/audio/tts/test.mp3
# 看响应头 X-Cache-Status: MISS (首次) → HIT (再次)
```

## 第四步：open-xiaoai 客户端配置

open-xiaoai 客户端需要连接 VPS 的 WebSocket 地址：

```
ws://your-domain.com/ws
# 或
wss://your-domain.com/ws
```

具体配置参考 [open-xiaoai 文档](https://github.com/idootop/open-xiaoai)。

## 数据流说明

### 音频播放 (TTS)

```
① 音箱唤醒 → WebSocket → VPS Nginx → WireGuard → VoiceGrow Server
② Server: ASR识别 → NLU解析 → Handler处理
③ Server: edge-tts合成 → /tmp临时文件 → 上传MinIO (tts/{hash}.mp3) → 删除临时文件
④ Server: 返回 play_url = https://your-domain.com/audio/tts/{hash}.mp3
⑤ 音箱请求音频 → VPS Nginx:
   ├─ 缓存命中 (HIT)  → 直接返回 (~30-80ms)
   └─ 缓存未命中 (MISS) → WireGuard → MinIO → 缓存 + 返回 (~80-200ms)
```

### 内容播放 (故事/音乐)

```
① DB 中存储: minio_path = "stories/bedtime/xxx.mp3" (对象路径)
② 查询时转换: get_public_url() → https://your-domain.com/audio/stories/bedtime/xxx.mp3
③ 音箱播放走同一 Nginx 反代 + 缓存路径
```

## URL 映射关系

| MinIO 对象路径 | 公网 URL | Nginx 转发目标 |
|---------------|---------|---------------|
| `tts/abc123.mp3` | `https://域名/audio/tts/abc123.mp3` | `http://10.0.0.2:9000/voicegrow/tts/abc123.mp3` |
| `stories/bedtime/xxx.mp3` | `https://域名/audio/stories/bedtime/xxx.mp3` | `http://10.0.0.2:9000/voicegrow/stories/bedtime/xxx.mp3` |
| `music/xxx.mp3` | `https://域名/audio/music/xxx.mp3` | `http://10.0.0.2:9000/voicegrow/music/xxx.mp3` |

## Nginx 缓存管理

### 缓存参数

| 参数 | 值 | 说明 |
|------|---|------|
| 缓存目录 | `/var/cache/nginx/voicegrow_audio` | VPS 本地磁盘 |
| 最大容量 | 1GB | 超出后 LRU 淘汰 |
| 过期时间 | 7天 | 7天无访问则淘汰 |
| 缓存键 | URI (忽略 query string) | TTS 按 hash 命名，天然去重 |

### 常用操作

```bash
# 查看缓存状态
du -sh /var/cache/nginx/voicegrow_audio

# 清空全部缓存
sudo rm -rf /var/cache/nginx/voicegrow_audio/*
sudo systemctl reload nginx

# 查看缓存命中率 (access log)
grep "audio" /var/log/nginx/access.log | awk '{print $NF}' | sort | uniq -c
# 需要在 Nginx log_format 中包含 $upstream_cache_status
```

### 自定义 access log 格式 (可选)

```nginx
# 在 http {} 块中添加:
log_format cache '$remote_addr - [$time_local] "$request" $status '
                 'cache:$upstream_cache_status $body_bytes_sent';

# 在 server {} 块中使用:
access_log /var/log/nginx/voicegrow.log cache;
```

## 故障排查

### 音箱播放无声音

```bash
# 1. 检查 URL 是否可达
curl -I https://your-domain.com/audio/tts/test.mp3

# 2. 检查 Nginx → MinIO 连通性
curl -I http://10.0.0.2:9000/voicegrow/tts/test.mp3   # 从 VPS 执行

# 3. 检查 WireGuard 隧道
sudo wg show

# 4. 检查 MinIO bucket 策略
mc anonymous get myminio/voicegrow
# 应该显示: Access permission for 'myminio/voicegrow' is 'download'
```

### Nginx 缓存不命中

```bash
# 检查响应头
curl -I https://your-domain.com/audio/tts/xxx.mp3
# X-Cache-Status: MISS (首次正常)
# 再次请求应为 HIT

# 检查缓存目录权限
ls -la /var/cache/nginx/voicegrow_audio
```

### TTS 合成失败

```bash
# 检查 VoiceGrow 日志
journalctl -u voicegrow -f | grep -i tts

# 常见原因:
# - edge-tts 网络不通 (需访问 Microsoft 服务)
# - MinIO 不可用 (上传失败)
# - MINIO_PUBLIC_BASE_URL 未配置 (ValueError)
# - /tmp/voicegrow_tts_tmp 目录无写权限
```

### WebSocket 连接断开

```bash
# 检查 Nginx WebSocket 配置
curl -i -N \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" \
  -H "Sec-WebSocket-Key: test" \
  https://your-domain.com/ws

# 检查 VPS → 内网 4399 端口连通
nc -zv 10.0.0.2 4399   # 从 VPS 执行
```

## 安全注意事项

1. **MinIO bucket 公开读取**: 当前整个 bucket 设置为公开只读。bucket 内仅存放音频内容，不含敏感数据。如未来存放用户数据，需改为按前缀设置策略。

2. **WireGuard**: 确保 VPS 防火墙只暴露必要端口 (80, 443, 51820/udp)。

3. **MinIO 管理端口**: MinIO Console (9001) 不应暴露到公网，仅内网访问。

4. **.env 文件**: 包含数据库密码和 API 密钥，不要提交到 Git。

## 环境变量速查

| 变量 | 必填 | 示例 | 说明 |
|------|-----|------|------|
| `TTS_BACKEND` | 是 | `edge-tts` | TTS 后端选择 |
| `MINIO_ENDPOINT` | 是 | `localhost:9000` | 内网 MinIO 地址 |
| `MINIO_ACCESS_KEY` | 是 | `minioadmin` | MinIO 访问密钥 |
| `MINIO_SECRET_KEY` | 是 | `minioadmin` | MinIO 密钥 |
| `MINIO_PUBLIC_BASE_URL` | 是 | `https://your-domain.com/audio` | VPS 公网音频 URL 前缀 |
| `MYSQL_HOST` | 是 | `localhost` | MySQL 地址 |
| `REDIS_HOST` | 是 | `localhost` | Redis 地址 |

完整配置参考 `.env.example`。
