/** 千问 ASR + CosyVoice 女声情感 TTS（流式优先，降低首包延迟）。 */

import { synthesizeSpeech, transcribeAudio } from "@/lib/api";

let currentAudio: HTMLAudioElement | null = null;
let currentObjectUrl: string | null = null;
let audioUnlocked = false;
let playToken = 0;

/** 静音短音：用于在用户手势里解锁浏览器自动播放策略 */
const SILENT_WAV =
  "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=";

function pickMimeType(): string {
  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
  ];
  for (const t of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(t)) {
      return t;
    }
  }
  return "audio/webm";
}

function extForMime(mime: string): string {
  if (mime.includes("mp4") || mime.includes("m4a")) return "mp4";
  if (mime.includes("ogg")) return "ogg";
  if (mime.includes("wav")) return "wav";
  return "webm";
}

export type MicRecorder = {
  stop: () => Promise<Blob>;
  abort: () => void;
};

/** 在点击/按住等用户手势中调用，避免后续 TTS 被浏览器拦截。 */
export async function unlockAudioPlayback(): Promise<void> {
  if (audioUnlocked) return;
  try {
    const a = new Audio(SILENT_WAV);
    a.volume = 0.01;
    await a.play();
    a.pause();
    a.src = "";
    audioUnlocked = true;
  } catch {
    /* 首次失败时等下次手势再试 */
  }
}

/** 按住说话：开始麦克风录音。 */
export async function startMicRecording(): Promise<MicRecorder> {
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    throw new Error("当前浏览器不支持麦克风录音，请使用 Chrome 并允许麦克风");
  }
  await unlockAudioPlayback();
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: true,
      noiseSuppression: true,
      channelCount: 1,
    },
  });
  const mimeType = pickMimeType();
  const chunks: BlobPart[] = [];
  const recorder = new MediaRecorder(stream, { mimeType });
  recorder.ondataavailable = (ev) => {
    if (ev.data && ev.data.size > 0) chunks.push(ev.data);
  };
  recorder.start(200);

  const stopTracks = () => {
    stream.getTracks().forEach((t) => t.stop());
  };

  return {
    stop: () =>
      new Promise<Blob>((resolve, reject) => {
        recorder.onstop = () => {
          stopTracks();
          resolve(new Blob(chunks, { type: mimeType }));
        };
        recorder.onerror = () => {
          stopTracks();
          reject(new Error("录音失败"));
        };
        try {
          if (recorder.state !== "inactive") recorder.stop();
          else {
            stopTracks();
            resolve(new Blob(chunks, { type: mimeType }));
          }
        } catch (e) {
          stopTracks();
          reject(e instanceof Error ? e : new Error("停止录音失败"));
        }
      }),
    abort: () => {
      try {
        if (recorder.state !== "inactive") recorder.stop();
      } catch {
        /* ignore */
      }
      stopTracks();
    },
  };
}

export async function recognizeBlob(blob: Blob): Promise<string> {
  const mime = blob.type || "audio/webm";
  const file = new File([blob], `voice.${extForMime(mime)}`, { type: mime });
  const res = await transcribeAudio(file);
  return (res.text || "").trim();
}

function cleanupAudio() {
  if (currentAudio) {
    try {
      currentAudio.pause();
      currentAudio.src = "";
    } catch {
      /* ignore */
    }
    currentAudio = null;
  }
  if (currentObjectUrl) {
    URL.revokeObjectURL(currentObjectUrl);
    currentObjectUrl = null;
  }
}

export function stopSpeaking() {
  playToken += 1;
  cleanupAudio();
}

function inferEmotionClient(text: string): string {
  if (/(抱歉|失败|连不上|没法|找不到|出错|暂时没有)/.test(text)) return "sad";
  if (/(注意|危险|请确认|小心|过高)/.test(text)) return "surprised";
  return "happy";
}

function b64ToUint8(b64: string): Uint8Array {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function playBlob(blob: Blob, volume: number, token: number) {
  if (token !== playToken) return;
  const url = URL.createObjectURL(blob);
  currentObjectUrl = url;
  await new Promise<void>((resolve, reject) => {
    if (token !== playToken) {
      URL.revokeObjectURL(url);
      resolve();
      return;
    }
    const audio = new Audio(url);
    currentAudio = audio;
    audio.volume = Math.min(1, Math.max(0, volume));
    audio.onended = () => {
      cleanupAudio();
      resolve();
    };
    audio.onerror = () => {
      cleanupAudio();
      reject(new Error("音频播放失败"));
    };
    void audio.play().then(
      () => {
        audioUnlocked = true;
      },
      (err) => {
        cleanupAudio();
        reject(
          new Error(
            err instanceof Error && /NotAllowedError|not allowed/i.test(err.name + err.message)
              ? "浏览器拦截了自动播放，请先点一下「开启声音」再试"
              : "语音播报被拦截，请点击页面后再试",
          ),
        );
      },
    );
  });
}

/** 流式合成：HTTP SSE 收齐后立刻播（首包延迟低于整包 URL 下载）。 */
async function speakStream(text: string, volume: number, emotion: string, token: number) {
  const res = await fetch("/api/tts/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, emotion }),
  });
  if (!res.ok || !res.body) {
    throw new Error(`tts stream ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  const parts: Uint8Array[] = [];
  let mime = "audio/mpeg";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (token !== playToken) {
      try {
        await reader.cancel();
      } catch {
        /* ignore */
      }
      return;
    }
    buf += decoder.decode(value, { stream: true });
    const blocks = buf.split("\n\n");
    buf = blocks.pop() || "";
    for (const block of blocks) {
      const line = block
        .split("\n")
        .map((l) => l.trim())
        .find((l) => l.startsWith("data:"));
      if (!line) continue;
      let ev: { type?: string; data?: string; mime?: string; error?: string } = {};
      try {
        ev = JSON.parse(line.slice(5).trim());
      } catch {
        continue;
      }
      if (ev.type === "error") throw new Error(ev.error || "TTS 流失败");
      if (ev.type === "audio" && ev.data) {
        if (ev.mime) mime = ev.mime;
        parts.push(b64ToUint8(ev.data));
      }
    }
  }

  if (token !== playToken) return;
  if (!parts.length) throw new Error("语音合成未返回音频");

  const total = parts.reduce((n, p) => n + p.length, 0);
  const merged = new Uint8Array(total);
  let off = 0;
  for (const p of parts) {
    merged.set(p, off);
    off += p.length;
  }
  await playBlob(new Blob([merged.buffer as ArrayBuffer], { type: mime }), volume, token);
}

/** 云端 TTS 播报；女声 + 情感；优先流式。volume 为 0–1。 */
export async function speakText(text: string, volume = 1) {
  const clean = text
    .replace(/^>.*$/gm, "")
    .replace(/[#*`_]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 90);
  if (!clean) return;

  stopSpeaking();
  const token = playToken;
  await unlockAudioPlayback();
  const emotion = inferEmotionClient(clean);

  try {
    await speakStream(clean, volume, emotion, token);
  } catch {
    if (token !== playToken) return;
    // 流式失败 → 整包女声情感合成
    const res = await synthesizeSpeech(clean, undefined, emotion);
    if (!res.audio_base64) throw new Error("语音合成未返回音频");
    const bytes = b64ToUint8(res.audio_base64);
    await playBlob(new Blob([bytes], { type: res.mime || "audio/mpeg" }), volume, token);
  }
}
