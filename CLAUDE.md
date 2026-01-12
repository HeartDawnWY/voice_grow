# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**VoiceGrow (声伴成长)** is a voice-activated learning and entertainment platform built on a modified Xiaomi XiaoAI smart speaker. The system uses voice as the primary interaction method, targeting children's education (stories, music, English learning) and intelligent conversation.

## Technical Stack

- **Server**: Python 3.10+, FastAPI
- **Client**: [open-xiaoai](https://github.com/idootop/open-xiaoai) Rust client (已实现，无需开发)
- **Supported Devices**: 小爱音箱 Pro (LX06), Xiaomi Smart Speaker Pro (OH2P) - 仅支持这两款
- **ASR**: faster-whisper (local Whisper model)
- **Wake Word**: 使用原有"小爱同学"（MVP阶段）
- **TTS**: Azure Speech Service (cloud)
- **LLM**: OpenAI GPT / Claude / 通义千问 (cloud API)
- **Database**: MySQL 8.0 (metadata)
- **Object Storage**: MinIO (audio files)
- **Communication**: WebSocket on port 4399

## Architecture

```
[小爱音箱 Pro / Smart Speaker Pro]
        │ (open-xiaoai Rust Client)
        │ - 麦克风音频流转发
        │ - 设备事件传输
        │ - 执行服务端命令
        │
        │ WebSocket (port 4399)
        ▼
[VoiceGrow Server]
        → ASR (Whisper, local)
        → NLU (Intent Recognition)
        → Handler (Story/Music/English/Chat)
        → Content Service (MySQL + MinIO)
        → TTS (Azure, cloud)
        → Response back to client (MinIO URLs)
        │
        ├──[MySQL]──(内容元数据)
        └──[MinIO]──(音频文件存储)
```

## Project Structure

```
voice_grow/
├── 基本设计/                    # Design documents
│   ├── 01_产品需求文档_PRD.md   # Product requirements
│   ├── 02_技术需求文档.md       # Technical requirements
│   ├── 03_系统架构文档.md       # System architecture
│   └── 04_接口规格说明.md       # API specifications
├── server/                      # Server code (to be created)
│   ├── app/
│   │   ├── api/                 # API routes (WebSocket on 4399, HTTP on 8000)
│   │   ├── core/                # ASR, NLU, TTS, LLM services
│   │   ├── services/            # Business logic (story, music, english, chat)
│   │   │   └── minio_service.py # MinIO object storage client
│   │   └── models/              # Data models (SQLAlchemy for MySQL)
└── tests/                       # Test files

# Client: 使用 open-xiaoai 项目，无需在本项目开发
# https://github.com/idootop/open-xiaoai
```

## Key Design Decisions

1. **Existing Client**: 使用 open-xiaoai Rust 客户端，无需自行开发
2. **Local ASR**: Privacy-first approach using Whisper locally
3. **Cloud TTS/LLM**: Quality over latency for synthesis and conversation
4. **Hybrid NLU**: Rule-based matching for common intents, LLM fallback for complex queries
5. **Plugin-based handlers**: Extensible content handlers for future features
6. **MVP Wake Word**: 先用原有"小爱同学"，后续扩展自定义唤醒词
7. **MinIO Object Storage**: Audio files stored in MinIO, accessed via presigned URLs
8. **MySQL Metadata**: Content metadata in MySQL for efficient querying and indexing

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
- Audio content stored in MinIO with presigned URLs for playback
- Metadata stored in MySQL with indexes for efficient content retrieval
- Content safety filtering required for LLM outputs
- Target response latency: ASR < 2s, TTS < 1s, E2E < 3s

## Content Storage

**MinIO Bucket Structure:**
```
voicegrow-bucket/
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
