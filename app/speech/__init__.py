# -*- coding: utf-8 -*-
"""百炼语音：ASR（千问）与 TTS（CosyVoice 女声情感）。"""
from .asr import transcribe_audio
from .tts import infer_emotion, iter_synthesize_stream, synthesize_speech

__all__ = ["transcribe_audio", "synthesize_speech", "iter_synthesize_stream", "infer_emotion"]
