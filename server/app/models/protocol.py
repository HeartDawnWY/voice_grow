"""
open-xiaoai 通信协议数据模型

基于 open-xiaoai 项目的实际协议分析
WebSocket 消息格式: JSON (Event/Request/Response) + Binary (Stream)
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Any, Dict
import uuid
import json


class MessageType(Enum):
    """消息类型枚举"""
    REQUEST = "request"      # 服务端 → 客户端 (命令)
    RESPONSE = "response"    # 客户端 → 服务端 (命令响应)
    EVENT = "event"          # 客户端 → 服务端 (事件通知)
    STREAM = "stream"        # 客户端 → 服务端 (二进制流)


class PlayingState(Enum):
    """播放状态枚举"""
    PLAYING = "Playing"
    PAUSED = "Paused"
    IDLE = "Idle"

    @classmethod
    def from_str(cls, value: str) -> "PlayingState":
        """从字符串转换"""
        mapping = {
            "Playing": cls.PLAYING,
            "playing": cls.PLAYING,
            "Paused": cls.PAUSED,
            "paused": cls.PAUSED,
            "Idle": cls.IDLE,
            "idle": cls.IDLE,
        }
        return mapping.get(value, cls.IDLE)


class ListeningState(Enum):
    """监听状态机"""
    IDLE = "idle"               # 空闲，等待唤醒
    WOKEN = "woken"             # 已唤醒，准备接收音频
    LISTENING = "listening"     # 正在接收音频
    PROCESSING = "processing"   # 正在处理 (ASR + NLU)
    RESPONDING = "responding"   # 正在响应 (TTS 播放)


@dataclass
class Event:
    """
    客户端上报的事件

    事件类型:
    - kws: 唤醒词检测, data="小爱同学"
    - playing: 播放状态, data="Playing"/"Paused"/"Idle"
    - instruction: 客户端ASR结果 (服务端ASR模式下仅作参考)
    """
    id: str
    event: str                          # 事件类型: kws, playing, instruction
    data: Optional[Any] = None

    @classmethod
    def parse(cls, data: Dict[str, Any]) -> "Event":
        """从 JSON 数据解析事件"""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            event=data["event"],
            data=data.get("data")
        )

    def is_wake_word(self) -> bool:
        """是否为唤醒词事件"""
        return self.event == "kws"

    def is_playing_event(self) -> bool:
        """是否为播放状态事件"""
        return self.event == "playing"

    def is_instruction(self) -> bool:
        """是否为指令事件 (客户端ASR结果)"""
        return self.event == "instruction"

    def get_playing_state(self) -> Optional[PlayingState]:
        """获取播放状态"""
        if self.event == "playing" and isinstance(self.data, str):
            return PlayingState.from_str(self.data)
        return None

    def get_instruction_text(self) -> Optional[str]:
        """
        获取指令文本 (客户端ASR结果)

        open-xiaoai instruction 事件数据格式:
        1. NewLine (流式结果): {"NewLine": "{\"header\":{...},\"payload\":{...}}"}
           内层 JSON payload.results[].text 为识别文本
        2. NewFile: "NewFile" (新的ASR片段，忽略)

        也兼容扁平格式:
        {"namespace":"SpeechRecognizer","name":"RecognizeResult","payload":{"results":[{"text":"..."}]}}
        """
        info = self._parse_instruction_payload()
        return info[0] if info else None

    def is_instruction_final(self) -> bool:
        """ASR 结果是否为最终结果 (is_final=true 或 is_stop=true)

        当检测到 is_final 或 is_stop 时，说明用户已说完，
        可以立即开始处理而无需等待去抖定时器。
        """
        info = self._parse_instruction_payload()
        return info[1] if info else False

    def is_cloud_playback_command(self) -> bool:
        """是否为云端播放/TTS 执行命令

        小米云端处理用户请求后，会通过 instruction 事件下发执行指令:
        - AudioPlayer/Play: 播放音乐列表
        - SpeechSynthesizer/Speak: 云端 TTS 播报

        当我们的 pipeline 正在处理时，需要拦截这些命令防止云端抢先播放。
        """
        if self.event != "instruction" or not isinstance(self.data, dict):
            return False

        new_line = self.data.get("NewLine")
        if not new_line:
            return False

        try:
            inner = json.loads(new_line)
            header = inner.get("header", {})
            ns = header.get("namespace", "")
            name = header.get("name", "")
            return (ns, name) in {
                ("AudioPlayer", "Play"),
                ("SpeechSynthesizer", "Speak"),
            }
        except (json.JSONDecodeError, TypeError, KeyError):
            return False

    def _parse_instruction_payload(self) -> Optional[tuple]:
        """解析 instruction 事件的 ASR payload

        Returns:
            (text, is_final) 元组，或 None
        """
        if self.event != "instruction":
            return None

        # "NewFile" 标记 - 新片段开始，无文本
        if self.data == "NewFile":
            return None

        if not isinstance(self.data, dict):
            return None

        # open-xiaoai 格式: {"NewLine": "<escaped_json>"}
        if "NewLine" in self.data:
            try:
                inner = json.loads(self.data["NewLine"])
                payload = inner.get("payload", {})
                results = payload.get("results", [])
                if results and isinstance(results, list) and len(results) > 0:
                    text = results[0].get("text")
                    is_final = payload.get("is_final", False) or results[0].get("is_stop", False)
                    return (text, is_final)
            except (json.JSONDecodeError, TypeError, KeyError):
                return None

        # 兼容扁平格式
        payload = self.data.get("payload", {})
        results = payload.get("results", [])
        if results and isinstance(results, list) and len(results) > 0:
            text = results[0].get("text")
            is_final = payload.get("is_final", False) or results[0].get("is_stop", False)
            return (text, is_final)

        return None


@dataclass
class Stream:
    """
    客户端上报的二进制流

    用于音频数据传输 (tag="record")
    """
    id: str
    tag: str                            # 流标签: record
    data: bytes                         # 二进制音频数据
    metadata: Optional[Dict] = None     # 可选元数据

    def is_audio_stream(self) -> bool:
        """是否为音频流"""
        return self.tag == "record"


@dataclass
class Request:
    """
    服务端发送的命令请求

    open-xiaoai Rust 客户端仅注册 6 个 RPC handler:
    - run_shell: 执行 shell 脚本, payload=纯字符串 (非对象)
    - start_recording: 启动 arecord 录音, payload=AudioConfig
    - stop_recording: 停止录音
    - start_play: 启动 aplay 播放, payload=AudioConfig
    - stop_play: 停止播放
    - get_version: 获取版本号

    其他所有操作 (abort_xiaoai, pause, play_url 等) 均通过
    run_shell 发送对应的 shell 命令实现 (与 SpeakerManager 一致)。
    """
    id: str
    command: str                        # 命令名称
    payload: Optional[Any] = None

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {"id": self.id, "command": self.command}
        if self.payload is not None:
            result["payload"] = self.payload
        return result

    def to_json(self) -> str:
        """转换为 JSON 字符串 (open-xiaoai 包装格式)"""
        return json.dumps({"Request": self.to_dict()}, ensure_ascii=False)

    @classmethod
    def play_url(cls, url: str, block: bool = False) -> "Request":
        """播放音频 URL (通过 ubus mediaplayer)"""
        return cls(
            id=str(uuid.uuid4()),
            command="run_shell",
            payload=f'ubus call mediaplayer player_play_url \'{{"url":"{url}","type": 1}}\''
        )

    @classmethod
    def play_text(cls, text: str, block: bool = False) -> "Request":
        """TTS 播放 (使用设备内置 tts_play.sh)"""
        safe_text = text.replace("'", "'\\''")
        return cls(
            id=str(uuid.uuid4()),
            command="run_shell",
            payload=f"/usr/sbin/tts_play.sh '{safe_text}'"
        )

    @classmethod
    def play(cls) -> "Request":
        """继续播放 (mphelper play)"""
        return cls(
            id=str(uuid.uuid4()),
            command="run_shell",
            payload="mphelper play"
        )

    @classmethod
    def pause(cls) -> "Request":
        """暂停播放 (mphelper pause)"""
        return cls(
            id=str(uuid.uuid4()),
            command="run_shell",
            payload="mphelper pause"
        )

    @classmethod
    def get_play_status(cls) -> "Request":
        """获取播放状态 (mphelper mute_stat)"""
        return cls(
            id=str(uuid.uuid4()),
            command="run_shell",
            payload="mphelper mute_stat"
        )

    @classmethod
    def mic_on(cls) -> "Request":
        """开启麦克风"""
        return cls(
            id=str(uuid.uuid4()),
            command="run_shell",
            payload="ubus -t1 -S call pnshelper event_notify '{\"src\":3, \"event\":7}' 2>&1"
        )

    @classmethod
    def mic_off(cls) -> "Request":
        """关闭麦克风"""
        return cls(
            id=str(uuid.uuid4()),
            command="run_shell",
            payload="ubus -t1 -S call pnshelper event_notify '{\"src\":3, \"event\":8}' 2>&1"
        )

    @classmethod
    def wake_up(cls, silent: bool = False) -> "Request":
        """唤醒设备 (模拟唤醒事件)"""
        if silent:
            script = "ubus call pnshelper event_notify '{\"src\":1,\"event\":0}'"
        else:
            script = (
                "ubus call pnshelper event_notify '{\"src\":3, \"event\":7}' && "
                "sleep 0.1 && "
                "ubus call pnshelper event_notify '{\"src\":3, \"event\":8}'"
            )
        return cls(
            id=str(uuid.uuid4()),
            command="run_shell",
            payload=script
        )

    @classmethod
    def abort_xiaoai(cls) -> "Request":
        """中断原生小爱 (重启 mico_aivs_lab 服务)"""
        return cls(
            id=str(uuid.uuid4()),
            command="run_shell",
            payload="/etc/init.d/mico_aivs_lab restart >/dev/null 2>&1"
        )

    @classmethod
    def ask_xiaoai(cls, text: str) -> "Request":
        """发送文字给原生小爱 NLP"""
        safe_text = text.replace('"', '\\"')
        return cls(
            id=str(uuid.uuid4()),
            command="run_shell",
            payload=f'ubus call mibrain ai_service \'{{"tts":1,"nlp":1,"nlp_text":"{safe_text}"}}\''
        )

    @classmethod
    def get_device_model(cls) -> "Request":
        """获取设备型号"""
        return cls(
            id=str(uuid.uuid4()),
            command="run_shell",
            payload="echo $(micocfg_model)"
        )

    @classmethod
    def get_device_sn(cls) -> "Request":
        """获取设备序列号"""
        return cls(
            id=str(uuid.uuid4()),
            command="run_shell",
            payload="echo $(micocfg_sn)"
        )

    @classmethod
    def run_shell(cls, script: str) -> "Request":
        """执行 shell 脚本 (payload 为纯字符串)"""
        return cls(
            id=str(uuid.uuid4()),
            command="run_shell",
            payload=script
        )

    @classmethod
    def set_volume(cls, level: int) -> "Request":
        """设置音量 (0-100)"""
        level = max(0, min(100, level))
        return cls(
            id=str(uuid.uuid4()),
            command="run_shell",
            payload=f"ubus call player_command volume_ctrl '{{\"action\":\"set\",\"value\":{level}}}'"
        )

    @classmethod
    def volume_up(cls, step: int = 10) -> "Request":
        """音量增大"""
        return cls(
            id=str(uuid.uuid4()),
            command="run_shell",
            payload=f"ubus call player_command volume_ctrl '{{\"action\":\"up\",\"value\":{step}}}'"
        )

    @classmethod
    def volume_down(cls, step: int = 10) -> "Request":
        """音量减小"""
        return cls(
            id=str(uuid.uuid4()),
            command="run_shell",
            payload=f"ubus call player_command volume_ctrl '{{\"action\":\"down\",\"value\":{step}}}'"
        )

    @classmethod
    def start_recording(
        cls,
        pcm: str = "noop",
        sample_rate: int = 16000,
        channels: int = 1,
        bits_per_sample: int = 16,
        period_size: int = 360,
        buffer_size: int = 1440,
    ) -> "Request":
        """启动本地录音 (直接 RPC，非 run_shell)

        通过 open-xiaoai 的 start_recording RPC 命令，让客户端从
        共享 ALSA 设备 (dsnoop) 捕获麦克风音频，通过 WebSocket
        二进制帧发送到服务端。

        注意: pcm="noop" 是共享捕获设备，云端同时也能接收音频。
        需要配合 abort_xiaoai() 阻止云端处理。
        """
        return cls(
            id=str(uuid.uuid4()),
            command="start_recording",
            payload={
                "pcm": pcm,
                "sample_rate": sample_rate,
                "channels": channels,
                "bits_per_sample": bits_per_sample,
                "period_size": period_size,
                "buffer_size": buffer_size,
            }
        )

    @classmethod
    def stop_recording(cls) -> "Request":
        """停止本地录音"""
        return cls(id=str(uuid.uuid4()), command="stop_recording")

    @classmethod
    def start_play(
        cls,
        pcm: str = "noop",
        sample_rate: int = 24000,
        channels: int = 1,
        bits_per_sample: int = 16,
    ) -> "Request":
        """启动本地播放（预留，暂不使用）"""
        return cls(
            id=str(uuid.uuid4()),
            command="start_play",
            payload={
                "pcm": pcm,
                "sample_rate": sample_rate,
                "channels": channels,
                "bits_per_sample": bits_per_sample,
            }
        )

    @classmethod
    def stop_play(cls) -> "Request":
        """停止本地播放"""
        return cls(id=str(uuid.uuid4()), command="stop_play")


@dataclass
class Response:
    """
    客户端返回的命令响应

    code: 0=成功, -1=失败
    """
    id: str
    code: Optional[int] = None          # 0=成功, -1=失败
    msg: Optional[str] = None
    data: Optional[Any] = None

    @classmethod
    def parse(cls, data: Dict[str, Any]) -> "Response":
        """从 JSON 数据解析响应"""
        return cls(
            id=data.get("id", ""),
            code=data.get("code"),
            msg=data.get("msg"),
            data=data.get("data")
        )

    def is_success(self) -> bool:
        """是否成功"""
        return self.code == 0

    def is_failure(self) -> bool:
        """是否失败"""
        return self.code == -1


def parse_json_message(data: str) -> Optional[Event | Response]:
    """
    解析 JSON 消息

    open-xiaoai 包装格式:
    - {"Event": {"id": "...", "event": "...", "data": ...}}
    - {"Response": {"id": "...", "code": ..., "data": ...}}
    也兼容扁平格式 (无包装)
    """
    try:
        json_data = json.loads(data)

        # open-xiaoai 包装格式: {"Event": {...}}
        if "Event" in json_data:
            return Event.parse(json_data["Event"])

        # open-xiaoai 包装格式: {"Response": {...}}
        if "Response" in json_data:
            return Response.parse(json_data["Response"])

        # 兼容扁平格式
        if "event" in json_data:
            return Event.parse(json_data)
        if "code" in json_data or "id" in json_data:
            return Response.parse(json_data)

        return None
    except json.JSONDecodeError:
        return None


def parse_binary_message(data: bytes) -> Optional[Stream]:
    """解析二进制 WebSocket 消息为 Stream 对象

    open-xiaoai 客户端在 start_recording 模式下发送的二进制帧格式:
    JSON 序列化的 Stream 结构:
      {"id":"...","tag":"record","bytes":[...],"data":null}

    Rust Vec<u8> 经 serde_json 序列化为 JSON 数组 [0-255]，
    每两个字节组成一个 S16_LE 采样。直接还原为 Python bytes 即可。

    如果解析失败，返回 None（调用方可回退为 raw PCM）。
    """
    try:
        json_data = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(json_data, dict):
        return None

    tag = json_data.get("tag")
    if not tag:
        return None

    stream_id = json_data.get("id", str(uuid.uuid4()))

    # 提取 PCM 数据: "bytes" 字段是 u8 数组（原始字节 0-255）
    raw_bytes = json_data.get("bytes")
    if isinstance(raw_bytes, list):
        try:
            pcm_data = bytes(raw_bytes)
        except (TypeError, ValueError):
            pcm_data = b""
    elif isinstance(raw_bytes, bytes):
        pcm_data = raw_bytes
    else:
        pcm_data = b""

    return Stream(
        id=stream_id,
        tag=tag,
        data=pcm_data,
        metadata=json_data.get("data"),
    )
