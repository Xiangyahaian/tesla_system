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
};

export type VehicleStateSummary = {
  climate_power?: boolean;
  temp?: number;
  fan?: number;
  volume?: number;
  music?: {
    playing?: boolean;
    artist?: string | null;
    title?: string | null;
  };
  navigation?: {
    navigating?: boolean;
    destination?: string | null;
    eta_min?: number | null;
  };
  speed_kmh?: number;
  gear?: string;
  pending?: boolean;
  session_id?: string;
  apps?: {
    active?: string | null;
  };
};

export type ConfirmPayload = {
  message: string;
  summary: string;
  risk: string;
  tool_calls?: unknown[];
};

export type CabinStateSnapshot = {
  climate?: {
    power?: boolean;
    zones?: Record<string, { temp?: number; fan?: number; on?: boolean }>;
  };
  media?: {
    volume?: number;
    muted?: boolean;
    music?: { playing?: boolean; artist?: string | null; title?: string | null };
  };
  navigation?: {
    navigating?: boolean;
    destination?: string | null;
    eta_min?: number | null;
  };
  dynamics?: { speed_kmh?: number; gear?: string };
  apps?: { active?: string | null; running?: string[] };
  seats?: {
    heat?: Record<string, { enable?: boolean; level?: number }>;
    steering_wheel_heat?: { enable?: boolean; level?: number };
  };
};
