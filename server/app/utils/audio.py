"""
音频工具函数

PCM/WAV 格式转换和音频信息获取
"""

import io
import struct
import wave


def pcm_to_wav(
    pcm_data: bytes,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """
    将 PCM 原始数据转换为 WAV 格式

    Args:
        pcm_data: PCM 原始音频数据
        sample_rate: 采样率
        channels: 声道数
        sample_width: 采样位宽 (字节)

    Returns:
        WAV 格式的字节数据
    """
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def get_audio_duration(
    data: bytes,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_width: int = 2,
) -> float:
    """
    根据 PCM 参数计算音频时长

    Args:
        data: PCM 音频数据
        sample_rate: 采样率
        channels: 声道数
        sample_width: 采样位宽 (字节)

    Returns:
        时长 (秒)
    """
    bytes_per_second = sample_rate * channels * sample_width
    if bytes_per_second == 0:
        return 0.0
    return len(data) / bytes_per_second


def get_wav_duration(wav_data: bytes) -> float:
    """
    获取 WAV 文件时长

    Args:
        wav_data: WAV 格式字节数据

    Returns:
        时长 (秒)
    """
    buf = io.BytesIO(wav_data)
    with wave.open(buf, "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        if rate == 0:
            return 0.0
        return frames / rate


def convert_sample_rate(
    data: bytes,
    from_rate: int,
    to_rate: int,
    channels: int = 1,
    sample_width: int = 2,
) -> bytes:
    """
    简单的采样率转换 (线性插值)

    Args:
        data: PCM 音频数据
        from_rate: 源采样率
        to_rate: 目标采样率
        channels: 声道数
        sample_width: 采样位宽 (字节)

    Returns:
        转换后的 PCM 数据
    """
    if from_rate == to_rate:
        return data

    # 解析样本
    fmt = "<h" if sample_width == 2 else "<b"
    sample_count = len(data) // (sample_width * channels)

    if sample_count == 0:
        return b""

    samples = struct.unpack(f"<{sample_count * channels}{'h' if sample_width == 2 else 'b'}", data)

    # 按声道分组
    channel_data = []
    for ch in range(channels):
        channel_data.append(samples[ch::channels])

    # 对每个声道进行线性插值
    ratio = from_rate / to_rate
    new_sample_count = int(sample_count / ratio)
    resampled_channels = []

    for ch_samples in channel_data:
        resampled = []
        for i in range(new_sample_count):
            src_pos = i * ratio
            idx = int(src_pos)
            frac = src_pos - idx

            if idx + 1 < len(ch_samples):
                value = ch_samples[idx] * (1 - frac) + ch_samples[idx + 1] * frac
            elif idx < len(ch_samples):
                value = ch_samples[idx]
            else:
                break

            if sample_width == 2:
                value = max(-32768, min(32767, int(value)))
            else:
                value = max(-128, min(127, int(value)))

            resampled.append(value)
        resampled_channels.append(resampled)

    # 交错声道
    result = []
    for i in range(len(resampled_channels[0])):
        for ch in range(channels):
            if i < len(resampled_channels[ch]):
                result.append(resampled_channels[ch][i])

    pack_fmt = f"<{len(result)}{'h' if sample_width == 2 else 'b'}"
    return struct.pack(pack_fmt, *result)
