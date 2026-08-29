export type VoicePhase = "idle" | "listening" | "thinking" | "acting" | "speaking";

export type TraceStep = {
  id: string;
  ts: number;
  type: string;
  title: string;
  detail?: Record<string, unknown>;
  status?: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  turnId?: string;
  steps?: TraceStep[];
  citePages?: (string | number)[];
  relatedImages?: { image_path: string; title?: string }[];
  contexts?: {
    index: number;
    title: string;
    page?: string | number | null;
    content: string;
    preview?: string;
    kind?: string;
    images?: { image_path: string; title?: string }[];
  }[];
};

export type ConfirmPayload = {
  message: string;
  summary: string;
  risk: string;
  confirm_kind?: string;
  tool_calls?: unknown[];
};

/** 中控高风险操作确认（非 Agent 对话） */
export type HmiConfirmPayload = {
  message: string;
  summary?: string;
};

export type ZoneClimate = { temp?: number; fan?: number; on?: boolean };
export type SeatNode = { enable?: boolean; level?: number; mode?: string };
export type WindowNode = { percent?: number };
export type DoorNode = { locked?: boolean };
export type LightNode = { brightness?: number; enable?: boolean; color?: string };

export type CabinStateSnapshot = {
  meta?: { version?: string; updated_at?: string; description?: string };
  dynamics?: {
    speed_kmh?: number;
    gear?: string;
    child_lock?: boolean;
    parked?: boolean;
    cruise_set_kmh?: number | null;
    cruise_target_kmh?: number | null;
  };
  climate?: {
    power?: boolean;
    mode?: string;
    direction?: string;
    recirculation?: boolean;
    zones?: Record<string, ZoneClimate>;
  };
  seats?: {
    heat?: Record<string, SeatNode>;
    ventilation?: Record<string, SeatNode>;
    massage?: Record<string, SeatNode>;
    steering_wheel_heat?: SeatNode;
  };
  cabin?: {
    windows?: Record<string, WindowNode>;
    doors?: Record<string, DoorNode>;
    lights?: Record<string, LightNode>;
    displays?: Record<string, { brightness?: number }>;
    trunk?: { open?: boolean };
    frunk?: { open?: boolean };
    charge_port?: { open?: boolean };
  };
    media?: {
    volume?: number;
    muted?: boolean;
    library?: {
      index: number;
      artist: string;
      title: string;
      album?: string | null;
      duration_sec?: number;
    }[];
    radio_stations?: {
      index: number;
      band: string;
      frequency: string | number;
      station_name: string;
      category?: string | null;
    }[];
    music?: {
      playing?: boolean;
      artist?: string | null;
      title?: string | null;
      album?: string | null;
      index?: number;
      position_sec?: number;
      duration_sec?: number;
    };
    radio?: {
      playing?: boolean;
      band?: string | null;
      frequency?: number | string | null;
      station_name?: string | null;
      index?: number;
    };
  };
  navigation?: {
    navigating?: boolean;
    mode?: "parked" | "cruising" | "navigating" | string;
    corridor_dest?: string | null;
    cruise_dir?: number | null;
    destination?: string | null;
    preference?: string;
    eta_min?: number | null;
    traffic?: string | null;
    provider?: string | null;
    origin?: { name?: string; lng?: number; lat?: number; location?: string } | null;
    origin_name?: string | null;
    distance_m?: number | null;
    remaining_m?: number | null;
    progress_m?: number | null;
    duration_sec?: number | null;
    polyline?: number[][];
    steps?: { instruction?: string; road?: string; distance?: number }[];
    heading_deg?: number | null;
    position?: { lng?: number; lat?: number; name?: string } | null;
    arrived?: boolean;
  };
  driving?: {
    mode?: string;
    battery_percent?: number;
    range_km?: number;
    adas?: {
      auto_hold?: boolean;
      acc?: boolean;
      autopark?: boolean;
      lane_keep?: boolean;
      collision_warning?: boolean;
    };
  };
  apps?: { active?: string | null; running?: string[]; installed?: string[] };
  connectivity?: {
    wifi?: { on?: boolean; ssid?: string | null; signal?: number };
    bluetooth?: boolean;
    cellular?: { on?: boolean; type?: string; carrier?: string; signal?: number };
  };
  notifications?: {
    message_access?: boolean;
    messages?: Array<{
      id?: string;
      app?: string;
      from?: string;
      text?: string;
      read?: boolean;
      ts?: string;
    }>;
    unread_messages?: number;
    latest_message?: { app?: string; from?: string; text?: string } | null;
    missed_calls?: number;
    phone_status?: string;
    phone_last?: string | null;
  };
  assistant?: {
    persona?: string;
    speech_rate?: string;
    speech_mode?: string;
    scene?: string | null;
  };
};
