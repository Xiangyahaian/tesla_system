import { useCallback, useEffect, useId, useRef, useState } from "react";
import { searchPlaces, type PlaceSearchHit } from "@/lib/api";

type Props = {
  kind: "origin" | "dest";
  value: string;
  placeholder: string;
  disabled?: boolean;
  sessionId: string;
  livePlaceName?: string;
  allowMyLocation?: boolean;
  onChange: (value: string) => void;
  onPick: (hit: PlaceSearchHit | { name: string; kind: "my_location" }) => void;
  onSubmit?: () => void;
  onFocusChange?: (focused: boolean) => void;
};

export function PlaceSearchField({
  kind,
  value,
  placeholder,
  disabled,
  sessionId,
  livePlaceName,
  allowMyLocation,
  onChange,
  onPick,
  onSubmit,
  onFocusChange,
}: Props) {
  const listId = useId();
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [hits, setHits] = useState<PlaceSearchHit[]>([]);
  const [active, setActive] = useState(-1);
  const reqRef = useRef(0);

  const close = useCallback(() => {
    setOpen(false);
    setActive(-1);
  }, []);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) close();
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [close]);

  useEffect(() => {
    if (!open || disabled) return;
    const q = value.trim();
    if (q.length < 1) {
      setHits([]);
      setLoading(false);
      return;
    }
    const myId = ++reqRef.current;
    setLoading(true);
    const timer = window.setTimeout(() => {
      void searchPlaces(q, sessionId, 8)
        .then((r) => {
          if (myId !== reqRef.current) return;
          setHits(r.pois || []);
          setActive(-1);
        })
        .catch(() => {
          if (myId !== reqRef.current) return;
          setHits([]);
        })
        .finally(() => {
          if (myId === reqRef.current) setLoading(false);
        });
    }, 260);
    return () => window.clearTimeout(timer);
  }, [value, open, disabled, sessionId]);

  const showMy = !!allowMyLocation && open;
  const hasPanel = open && (showMy || loading || hits.length > 0 || value.trim().length > 0);

  const selectHit = (hit: PlaceSearchHit) => {
    onPick(hit);
    onChange(hit.name);
    close();
  };

  const selectMy = () => {
    onPick({ name: livePlaceName || "当前位置", kind: "my_location" });
    onChange(livePlaceName || "当前位置");
    close();
  };

  return (
    <div
      className={`amap-place-field amap-place-field--${kind}${open ? " is-open" : ""}`}
      ref={wrapRef}
    >
      <i className="amap-place-dot" aria-hidden />
      <input
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        role="combobox"
        aria-expanded={hasPanel}
        aria-controls={listId}
        aria-autocomplete="list"
        autoComplete="off"
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => {
          setOpen(true);
          onFocusChange?.(true);
        }}
        onBlur={() => onFocusChange?.(false)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.preventDefault();
            close();
            return;
          }
          const extras = showMy ? 1 : 0;
          const total = extras + hits.length;
          if (e.key === "ArrowDown" && total > 0) {
            e.preventDefault();
            setOpen(true);
            setActive((i) => (i + 1) % total);
            return;
          }
          if (e.key === "ArrowUp" && total > 0) {
            e.preventDefault();
            setOpen(true);
            setActive((i) => (i <= 0 ? total - 1 : i - 1));
            return;
          }
          if (e.key === "Enter") {
            e.preventDefault();
            if (active === 0 && showMy) {
              selectMy();
              return;
            }
            const idx = showMy ? active - 1 : active;
            if (idx >= 0 && hits[idx]) {
              selectHit(hits[idx]);
              return;
            }
            onSubmit?.();
            close();
          }
        }}
      />
      {value && !disabled ? (
        <button
          type="button"
          className="amap-place-clear"
          aria-label="清除"
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => {
            onChange("");
            setHits([]);
            setOpen(true);
          }}
        >
          ×
        </button>
      ) : null}

      {hasPanel ? (
        <div className="amap-place-panel" id={listId} role="listbox">
          {showMy ? (
            <button
              type="button"
              role="option"
              className={`amap-place-hit amap-place-hit--loc${active === 0 ? " is-active" : ""}`}
              onMouseDown={(e) => e.preventDefault()}
              onClick={selectMy}
            >
              <em>我的位置</em>
              <span>{livePlaceName || "当前定位"}</span>
            </button>
          ) : null}

          {loading && hits.length === 0 ? (
            <div className="amap-place-empty">正在搜索…</div>
          ) : null}

          {!loading && value.trim() && hits.length === 0 ? (
            <div className="amap-place-empty">没有匹配地点</div>
          ) : null}

          {hits.map((hit, i) => {
            const optIndex = (showMy ? 1 : 0) + i;
            return (
              <button
                key={`${hit.location || hit.name}-${i}`}
                type="button"
                role="option"
                className={`amap-place-hit${active === optIndex ? " is-active" : ""}`}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => selectHit(hit)}
              >
                <em>{hit.name}</em>
                <span>{hit.address || "北京市"}</span>
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
