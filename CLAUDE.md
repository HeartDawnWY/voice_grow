# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**VoiceGrow (声伴成长)** is a voice-activated learning and entertainment platform built on a modified Xiaomi XiaoAI smart speaker. The system uses voice as the primary interaction method, targeting children's education (stories, music, English learning) and intelligent conversation.

## Technical Stack

- **Server**: Python 3.10+, FastAPI
- **Admin Frontend**: React 19 + TypeScript + Vite + TailwindCSS
- **Client**: [open-xiaoai](https://github.com/idootop/open-xiaoai) Rust client (已实现，无需开发)
- **Supported Devices**: 小爱音箱 Pro (LX06), Xiaomi Smart Speaker Pro (OH2P) - 仅支持这两款
- **ASR**: ai-manager STT API (远程 Whisper 服务，端口 10000)
- **Wake Word**: 使用原有"小爱同学"（MVP阶段）
- **TTS**: edge-tts (Microsoft Edge TTS，本地合成后上传 MinIO)
- **LLM**: ai-manager API (支持 Gemini / GPT / Claude 等模型)
- **Database**: MySQL 8.0 (metadata)
- **Object Storage**: MinIO (audio files, 通过 VPS Nginx 反代提供公网访问)
- **Cache**: Redis (会话/内容缓存)
- **Communication**: WebSocket on port 4399

## Deployment Architecture

```
┌──────────┐         ┌──────────────────────┐         ┌──────────────────────────┐
│  小爱音箱  │         │  外网 VPS              │         │  内网服务器                │
│          │  公网    │                      │  WG隧道  │                          │
│  play_url├────────►│  Nginx (:443)        ├────────►│  VoiceGrow Server (:4399)│
│  WebSocket│         │  ├ /audio/* → MinIO  │         │  ├ ASR (ai-manager STT)  │
│          │         │  └ /ws      → WS     │         │  ├ NLU                   │
│          │         │                      │         │  ├ TTS (edge-tts)        │
└──────────┘         │                      │         │  └ LLM (ai-manager)      │
                     │  音频缓存 (max 1GB)   │         │                          │
                     └──────────────────────┘         │  Admin Frontend (:3000)  │
                                                      │  MinIO (:9000)           │
                                                      │  MySQL (:3306)           │
                                                      │  Redis (:6379)           │
                                                      └──────────────────────────┘
```

**音频 URL 统一方案**: DB 中仅存储 MinIO 对象路径 (如 `tts/abc123.mp3`)，查询时通过 `get_public_url()` 拼接 `MINIO_PUBLIC_BASE_URL` 生成公网 URL，所有音频走 VPS Nginx 反代 + 缓存。

## Project Structure

```
voice_grow/
├── 基本设计/                    # Design documents
│   ├── 01_产品需求文档_PRD.md   # Product requirements
│   ├── 02_技术需求文档.md       # Technical requirements
│   ├── 03_系统架构文档.md       # System architecture
│   └── 04_接口规格说明.md       # API specifications
├── server/                      # Backend server
│   ├── app/
│   │   ├── api/                 # API routes (WebSocket on 4399, HTTP on 8000)
│   │   ├── core/                # ASR, NLU, TTS, LLM services
│   │   ├── services/            # Business logic (story, music, english, chat)
│   │   │   ├── minio_service.py # MinIO client (含 get_public_url)
│   │   │   └── content/         # 内容服务 (拆分为 base/query/manage)
│   │   └── models/              # Data models (SQLAlchemy for MySQL)
│   ├── Dockerfile
│   └── requirements.txt
├── admin/                       # Admin management frontend
│   ├── src/                     # React + TypeScript source
│   ├── Dockerfile               # Multi-stage build (Node + Nginx)
│   ├── nginx.conf               # Admin SPA nginx config
│   └── package.json
├── deploy/                      # Deployment configs
│   ├── nginx/voicegrow.conf     # VPS Nginx reverse proxy config
│   └── DEPLOY.md                # Deployment documentation
├── docker-compose.yml           # Server + Admin (外部 MySQL/MinIO/Redis)
├── .env.example                 # Environment variables template
└── tests/                       # Test files

# Client: 使用 open-xiaoai 项目，无需在本项目开发
# https://github.com/idootop/open-xiaoai
```

## Key Design Decisions

1. **Existing Client**: 使用 open-xiaoai Rust 客户端，无需自行开发
2. **Remote ASR**: ai-manager STT API (独立端口 10000)
3. **Local TTS**: edge-tts 本地合成后上传 MinIO，通过 VPS Nginx 反代提供公网访问
4. **VPS Reverse Proxy**: 音箱通过公网访问 VPS，VPS 通过 WireGuard 隧道转发到内网服务
5. **Public URL Pattern**: 统一使用 `MINIO_PUBLIC_BASE_URL` + 对象路径生成公网 URL
6. **Hybrid NLU**: Rule-based matching for common intents, LLM fallback for complex queries
7. **Plugin-based handlers**: Extensible content handlers for future features
8. **MVP Wake Word**: 先用原有"小爱同学"，后续扩展自定义唤醒词
9. **External Services**: MySQL/MinIO/Redis 使用现有实例，不在 docker-compose 中构建

## Core Intents

| Intent | Description | Example |
|--------|-------------|---------|
| play_story | Play stories | "讲个故事" |
| play_music | Play music | "播放儿歌" |
| english_learn | English learning | "学英语" |
| chat | Free conversation | "为什么天是蓝的" |
| control_* | Playback control | "暂停", "下一个" |

## Development Notes

- MVP focuses on: stories, music, basic English, simple chat
- Audio files stored in MinIO, DB 仅存对象路径，查询时生成公网 URL
- Metadata stored in MySQL with indexes for efficient content retrieval
- Content safety filtering required for LLM outputs
- Target response latency: ASR < 2s, TTS < 1s, E2E < 3s
- TTS 合成流程: edge-tts → /tmp 临时文件 → 上传 MinIO → 删除临时文件

## Content Storage

**MinIO Bucket Structure:**
```
voicegrow/
├── tts/           # TTS 合成音频 (hash 命名，自动去重)
├── stories/       # 故事音频
│   ├── bedtime/
│   ├── fairy_tale/
│   └── ...
├── music/         # 音乐文件
├── english/       # 英语学习音频
└── covers/        # 封面图片
```

**MySQL Tables:**
- `contents`: 内容元数据 (type, category, title, minio_path, duration, etc.)
- `play_history`: 播放历史

## Workflow Rules

- **代码审核必须**: 每次修改代码后，必须调用 `superpowers:requesting-code-review` 技能对本次修改进行代码审核。审核通过后任务才算完成。
