/** 千问 ASR + CosyVoice 女声情感 TTS（流式优先，降低首包延迟）。 */

import { synthesizeSpeech, transcribeAudio } from "@/lib/api";

let currentAudio: HTMLAudioElement | null = null;
let currentObjectUrl: string | null = null;
let audioUnlocked = false;
let playToken = 0;
let currentAudioCtx: AudioContext | null = null;
/** 用户主动暂停播报（可继续） */
let userPaused = false;

/** 静音短音：用于在用户手势里解锁浏览器自动播放策略 */
const SILENT_WAV =
  "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=";

function pickMimeType(): string {
  // Safari / macOS 通常只支持 mp4(aac)；Chrome 支持 webm(opus)
  const candidates = [
    "audio/mp4",
    "audio/mp4;codecs=mp4a.40.2",
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/aac",
    "audio/ogg;codecs=opus",
  ];
  const supported: string[] = [];
  for (const t of candidates) {
    try {
      if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(t)) {
        supported.push(t);
      }
    } catch {
      /* ignore */
    }
  }
  // Safari 优先 mp4；其余优先 webm
  const isApple =
    typeof navigator !== "undefined" &&
    (/Mac|iPhone|iPad|iPod/.test(navigator.platform) ||
      /Mac OS X|iPhone|iPad/.test(navigator.userAgent));
  if (isApple) {
    const mp4 = supported.find((t) => t.includes("mp4") || t.includes("aac"));
    if (mp4) return mp4;
  }
  const webm = supported.find((t) => t.includes("webm"));
  if (webm) return webm;
  if (supported[0]) return supported[0];
  // 不硬编码 webm：让浏览器选默认编码器（Safari 关键）
  return "";
}

function extForMime(mime: string): string {
  const m = (mime || "").toLowerCase();
  if (m.includes("mp4") || m.includes("m4a") || m.includes("aac")) return "mp4";
  if (m.includes("ogg") || m.includes("opus")) return "ogg";
  if (m.includes("wav")) return "wav";
  if (m.includes("mpeg") || m.includes("mp3")) return "mp3";
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

/** 无法调用 getUserMedia 时的原因（此时浏览器也不会弹出授权框）。 */
function micBlockedBeforePrompt(): string | null {
  if (typeof window !== "undefined" && !window.isSecureContext) {
    return "请用 https 或本机 localhost 打开后再使用语音";
  }
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    return "当前浏览器不支持语音输入，请使用 Chrome（Mac 上 Safari 也可，需允许麦克风）";
  }
  return null;
}

function micPermissionError(err: unknown): Error {
  const name = err instanceof DOMException ? err.name : "";
  const msg = err instanceof Error ? err.message : String(err);
  if (name === "NotAllowedError" || name === "PermissionDeniedError" || /denied|not allowed/i.test(msg)) {
    return new Error("需要允许麦克风才能语音输入，请在浏览器提示中选择「允许」");
  }
  if (name === "NotFoundError" || /not found|device/i.test(msg)) {
    return new Error("未检测到麦克风");
  }
  if (name === "NotReadableError") {
    return new Error("麦克风被占用，请稍后再试");
  }
  return err instanceof Error ? err : new Error("无法启动麦克风");
}

/**
 * 按住说话：开始麦克风录音。
 * 首次会直接弹出浏览器原生麦克风授权框（无应用内弹窗）。
 * macOS Safari 走 mp4/aac；Chrome 走 webm。
 */
export async function startMicRecording(): Promise<MicRecorder> {
  const blocked = micBlockedBeforePrompt();
  if (blocked) throw new Error(blocked);

  const unlockP = unlockAudioPlayback();
  let stream: MediaStream;
  try {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          channelCount: 1,
        },
      });
    } catch {
      // 部分 Mac 设备不接受 channelCount 等约束，退回默认麦克风
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    }
  } catch (e) {
    await unlockP.catch(() => undefined);
    throw micPermissionError(e);
  }
  await unlockP.catch(() => undefined);

  const preferred = pickMimeType();
  let mimeType = preferred;
  let recorder: MediaRecorder;
  try {
    recorder = mimeType
      ? new MediaRecorder(stream, { mimeType })
      : new MediaRecorder(stream);
  } catch {
    recorder = new MediaRecorder(stream);
    mimeType = recorder.mimeType || preferred || "audio/mp4";
  }
  // 以浏览器实际编码器为准（Safari 常写成 audio/mp4）
  mimeType = recorder.mimeType || mimeType || "audio/mp4";

  const chunks: BlobPart[] = [];
  recorder.ondataavailable = (ev) => {
    if (ev.data && ev.data.size > 0) chunks.push(ev.data);
  };
  // Safari 对 timeslice 支持不稳定；苹果设备用默认切片，停录时靠 onstop 收尾包
  const isApple =
    /Mac|iPhone|iPad|iPod/.test(navigator.platform) ||
    /Mac OS X|iPhone|iPad/.test(navigator.userAgent);
  try {
    if (isApple) recorder.start();
    else recorder.start(200);
  } catch {
    recorder.start();
  }

  const stopTracks = () => {
    stream.getTracks().forEach((t) => t.stop());
  };

  return {
    stop: () =>
      new Promise<Blob>((resolve, reject) => {
        const finish = () => {
          stopTracks();
          const type = mimeType || "audio/mp4";
          const blob = new Blob(chunks, { type });
          if (!blob.size) {
            reject(new Error("没听到声音，请按住多说一会儿再松手"));
            return;
          }
          resolve(blob);
        };
        recorder.onstop = finish;
        recorder.onerror = () => {
          stopTracks();
          reject(new Error("录音失败"));
        };
        try {
          if (recorder.state === "recording") {
            // 先 requestData 再 stop，提高 Safari 拿到最后一包的概率
            try {
              if (typeof recorder.requestData === "function") recorder.requestData();
            } catch {
              /* ignore */
            }
            recorder.stop();
          } else if (recorder.state === "inactive") {
            finish();
          } else {
            recorder.stop();
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
  userPaused = false;
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
  if (currentAudioCtx) {
    try {
      void currentAudioCtx.close();
    } catch {
      /* ignore */
    }
    currentAudioCtx = null;
  }
}

export function stopSpeaking() {
  userPaused = false;
  playToken += 1;
  cleanupAudio();
}

/** 暂停当前播报（生成流需另行 abort）。返回是否成功进入暂停。 */
export function pauseSpeaking(): boolean {
  if (currentAudio && !currentAudio.paused && !currentAudio.ended) {
    try {
      currentAudio.pause();
      userPaused = true;
      return true;
    } catch {
      return false;
    }
  }
  if (currentAudioCtx && currentAudioCtx.state === "running") {
    userPaused = true;
    void currentAudioCtx.suspend();
    return true;
  }
  return false;
}

/** 继续被暂停的播报 */
export async function resumeSpeaking(): Promise<boolean> {
  if (currentAudio && currentAudio.paused && !currentAudio.ended && currentAudio.src) {
    try {
      await currentAudio.play();
      userPaused = false;
      audioUnlocked = true;
      return true;
    } catch {
      return false;
    }
  }
  if (currentAudioCtx && currentAudioCtx.state === "suspended") {
    try {
      await currentAudioCtx.resume();
      userPaused = false;
      return true;
    } catch {
      return false;
    }
  }
  return false;
}

export function isSpeakingActive(): boolean {
  if (userPaused) return false;
  if (currentAudio && !currentAudio.paused && !currentAudio.ended) return true;
  if (currentAudioCtx && currentAudioCtx.state === "running") return true;
  return false;
}

export function isSpeakingPaused(): boolean {
  if (!userPaused) return false;
  if (currentAudio && currentAudio.paused && currentAudio.src && !currentAudio.ended) return true;
  if (currentAudioCtx && currentAudioCtx.state === "suspended") return true;
  return false;
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

/** PCM s16le：收到分片就排队开播，不必等整段。 */
async function playPcmLive(volume: number, sampleRate: number, token: number) {
  const AudioCtx =
    window.AudioContext ||
    (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  const ctx = new AudioCtx({ sampleRate });
  currentAudioCtx = ctx;
  if (ctx.state === "suspended") await ctx.resume();
  if (token !== playToken) {
    cleanupAudio();
    return null;
  }

  const gain = ctx.createGain();
  gain.gain.value = Math.min(1, Math.max(0, volume));
  gain.connect(ctx.destination);

  let nextStart = ctx.currentTime + 0.02;
  let leftover = new Uint8Array(0);
  let started = false;

  return {
    push(bytes: Uint8Array) {
      if (token !== playToken || !bytes.length) return;
      // 暂停时仍缓冲时间轴，恢复后从断点继续
      const merged = new Uint8Array(leftover.length + bytes.length);
      merged.set(leftover, 0);
      merged.set(bytes, leftover.length);
      const even = merged.length - (merged.length % 2);
      leftover = even < merged.length ? merged.slice(even) : new Uint8Array(0);
      if (even < 2) return;

      const copy = merged.slice(0, even);
      const view = new Int16Array(copy.buffer, copy.byteOffset, even / 2);
      const f32 = new Float32Array(view.length);
      for (let i = 0; i < view.length; i++) f32[i] = view[i] / 32768;
      const abuf = ctx.createBuffer(1, f32.length, sampleRate);
      abuf.copyToChannel(f32, 0);
      const src = ctx.createBufferSource();
      src.buffer = abuf;
      src.connect(gain);
      const when = Math.max(nextStart, ctx.currentTime + 0.005);
      src.start(when);
      nextStart = when + abuf.duration;
      started = true;
    },
    async finish() {
      if (token !== playToken) {
        cleanupAudio();
        return;
      }
      if (!started) throw new Error("语音合成未返回音频");
      // 暂停期间不要提前 cleanup：等用户继续或 stop
      while (token === playToken && userPaused) {
        await new Promise((r) => window.setTimeout(r, 120));
      }
      if (token !== playToken) {
        cleanupAudio();
        return;
      }
      const waitMs = Math.max(0, (nextStart - ctx.currentTime) * 1000) + 180;
      await new Promise<void>((resolve) => {
        window.setTimeout(() => {
          if (token === playToken && !userPaused) cleanupAudio();
          resolve();
        }, waitMs);
      });
    },
  };
}

/** 流式合成：PCM 首包即播；失败抛错由 speakText 回退整包 mp3。 */
async function speakStream(text: string, volume: number, emotion: string, token: number) {
  const res = await fetch("/api/tts/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, emotion, format: "pcm" }),
  });
  if (!res.ok || !res.body) {
    throw new Error(`tts stream ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let lineBuf = "";
  let sampleRate = 24000;
  let player: Awaited<ReturnType<typeof playPcmLive>> | null = null;
  const mp3Parts: Uint8Array[] = [];
  let asMp3 = false;

  try {
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
      lineBuf += decoder.decode(value, { stream: true });
      const blocks = lineBuf.split("\n\n");
      lineBuf = blocks.pop() || "";
      for (const block of blocks) {
        const line = block
          .split("\n")
          .map((l) => l.trim())
          .find((l) => l.startsWith("data:"));
        if (!line) continue;
        let ev: {
          type?: string;
          data?: string;
          mime?: string;
          error?: string;
          sample_rate?: number;
          format?: string;
        } = {};
        try {
          ev = JSON.parse(line.slice(5).trim());
        } catch {
          continue;
        }
        if (ev.type === "error") throw new Error(ev.error || "TTS 流失败");
        if (ev.type === "meta") {
          if (typeof ev.sample_rate === "number" && ev.sample_rate > 0) sampleRate = ev.sample_rate;
          const fmt = String(ev.format || "").toLowerCase();
          const mime = String(ev.mime || "").toLowerCase();
          asMp3 = fmt === "mp3" || mime.includes("mpeg") || mime.includes("mp3");
        }
        if (ev.type === "audio" && ev.data) {
          const bytes = b64ToUint8(ev.data);
          if (asMp3) {
            mp3Parts.push(bytes);
            continue;
          }
          if (!player) {
            player = await playPcmLive(volume, sampleRate, token);
            if (!player) return;
          }
          player.push(bytes);
        }
      }
    }

    if (asMp3) {
      if (!mp3Parts.length) throw new Error("语音合成未返回音频");
      const total = mp3Parts.reduce((n, p) => n + p.length, 0);
      const merged = new Uint8Array(total);
      let off = 0;
      for (const p of mp3Parts) {
        merged.set(p, off);
        off += p.length;
      }
      await playBlob(new Blob([merged.buffer as ArrayBuffer], { type: "audio/mpeg" }), volume, token);
      return;
    }

    if (!player) throw new Error("语音合成未返回音频");
    await player.finish();
  } finally {
    try {
      await reader.cancel();
    } catch {
      /* ignore */
    }
  }
}

/** 云端 TTS 播报；女声 + 情感；优先流式。volume 为 0–1。
 * interrupt=false 时不打断当前播报（用于续播后半段）。
 */
export async function speakText(
  text: string,
  volume = 1,
  opts?: { interrupt?: boolean },
) {
  const clean = text
    .replace(/^>.*$/gm, "")
    .replace(/[#*`_]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 160);
  if (!clean) return;

  if (opts?.interrupt !== false) {
    stopSpeaking();
  }
  const token = playToken;
  await unlockAudioPlayback();
  if (token !== playToken) return;
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
