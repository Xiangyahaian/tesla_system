# -*- coding: utf-8 -*-
"""追加式压缩验收：新用户+新会话，强制完成 ≥3 次 compaction。"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config
from app.agent.types import MessageRole
from app.llm.client import get_llm, probe_local_llm
from app.session.store import get_session_store


TOPICS = [
    ("我叫陆青川，在望京做机器人导航", "身份"),
    ("未婚妻叫沈晚棠，住朝阳大山子", "家人住址"),
    ("说话简洁一点，别客套", "人设"),
    ("以后叫我青川，习惯坐主驾", "称呼座位"),
    ("主驾默认21度，爱听周云蓬", "温度音乐"),
    ("打开主驾座椅加热两档", "座椅加热"),
    ("导航去798艺术区", "导航798"),
    ("音量调到30，播放周云蓬的杜甫", "媒体"),
    ("右后窗开20%，氛围灯蓝色", "车窗灯光"),
    ("公司搬到酒仙桥了", "公司变更"),
    ("结束导航，空调切eco", "结束导航"),
    ("附近找个能吃饭的京菜馆", "周边搜索"),
    ("记住我周四去攀岩", "记忆攀岩"),
    ("副驾温度调到22", "副驾温度"),
    ("打开儿童锁和车道保持", "ADAS"),
    ("查一下现在主驾温度", "查温度"),
    ("播放下一首，快进20秒", "媒体控制"),
    ("导航改去三里屯太古里", "改导航"),
    ("关掉座椅加热，开通风", "通风"),
    ("语气再专业一点", "人设调整"),
]


def _fill_block(sess, store, block_id: int, n_turns: int = 8) -> None:
    """写入足够多轮，保证超过 keep_recent_turns=5，从而可压缩。"""
    base = block_id * n_turns
    for i in range(n_turns):
        topic = TOPICS[(base + i) % len(TOPICS)]
        q = f"【段{block_id}-轮{i+1}】{topic[0]}"
        sess.transcript.append(MessageRole.USER, q)
        # 模拟 tool + assistant，拉长可压缩内容
        if i % 2 == 0:
            sess.transcript.append(
                MessageRole.TOOL,
                (f"工具结果#{block_id}.{i}：" + topic[1] + "；") * 40,
                tool="climate.get_state",
            )
        sess.transcript.append(
            MessageRole.ASSISTANT,
            f"【听】已处理：{topic[1]}。青川这边记下了。",
        )
    store.save(sess)


def main() -> int:
    probe = probe_local_llm(force=True)
    if not probe.get("ok"):
        print("本地模型不可用:", probe.get("error"))
        return 1

    store = get_session_store()
    nick = f"追加压缩测_{datetime.now().strftime('%m%d%H%M')}"
    home = store.ensure_user(nick)
    uid = str(home.slots.get("user_id") or home.user_id or "")
    sess = store.create_session(title="追加压缩三次验收", owner_id=uid)
    sid = sess.session_id
    store.save(sess)

    llm = get_llm("local")
    print(f"用户: {nick} ({uid})")
    print(f"会话: {sid}")
    print(f"日志: {sess.root / 'session.jsonl'}")
    print(f"keep_turns={config.AGENT_KEEP_RECENT_TURNS} soft={config.AGENT_SOFT_CONTEXT_CHARS}")
    print("-" * 60)

    reports = []
    for round_i in range(3):
        _fill_block(sess, store, round_i, n_turns=8)
        before_n = len(sess.transcript.load())
        t0 = time.perf_counter()
        report = store.maybe_compact(sess, llm=llm, force=True)
        ms = int((time.perf_counter() - t0) * 1000)
        after = sess.transcript.load()
        n_comp = sum(1 for m in after if m.role == MessageRole.COMPACTION)
        ok = bool(report and "append_compact" in (report.layers or []))
        summary = (report.summary if report else "")[:120]
        print(
            f"[compact#{round_i+1}] ok={ok} msgs {before_n}->{len(after)} "
            f"compactions={n_comp} {ms}ms layers={report.layers if report else []}"
        )
        print(f"  summary: {summary}")
        reports.append(
            {
                "round": round_i + 1,
                "ok": ok,
                "ms": ms,
                "layers": list(report.layers) if report else [],
                "summary": report.summary if report else "",
                "total_msgs": len(after),
                "compaction_count": n_comp,
            }
        )
        if not ok:
            print("压缩失败，中止")
            return 2
        # 压缩后再聊两轮，验证追加在 compaction 之后
        sess.transcript.append(MessageRole.USER, f"压缩{round_i+1}后还在吗，回一个字")
        sess.transcript.append(MessageRole.ASSISTANT, "在")
        store.save(sess)

    # 再填一段并第四次？用户要三次以上，三次已够；可选再来一次证明可继续
    _fill_block(sess, store, 3, n_turns=7)
    report4 = store.maybe_compact(sess, llm=llm, force=True)
    after = sess.transcript.load()
    n_comp = sum(1 for m in after if m.role == MessageRole.COMPACTION)
    print("-" * 60)
    print(f"第四次压缩: layers={report4.layers if report4 else []} total_compactions={n_comp}")

    window = sess.transcript.load_for_context(keep_turns=config.AGENT_KEEP_RECENT_TURNS)
    print(f"上下文窗口条数: {len(window)} (应含1条最新compaction+最近轮)")
    print("窗口角色:", [m.role.value for m in window])
    if window and window[0].role == MessageRole.COMPACTION:
        print("最新摘要预览:", window[0].content[:200])

    log_path = sess.root / "session.jsonl"
    legacy_tr = sess.root / "transcript.jsonl"
    legacy_sj = sess.root / "session.json"
    print(f"session.jsonl 存在: {log_path.exists()}")
    print(f"旧文件残留 transcript.jsonl={legacy_tr.exists()} session.json={legacy_sj.exists()}")

    out = {
        "nickname": nick,
        "user_id": uid,
        "session_id": sid,
        "session_log": str(log_path),
        "compaction_count": n_comp,
        "total_messages": len(after),
        "context_window_roles": [m.role.value for m in window],
        "reports": reports,
        "fourth": {
            "layers": list(report4.layers) if report4 else [],
            "summary": (report4.summary if report4 else "")[:300],
        },
        "latest_summary": next(
            (m.content for m in reversed(after) if m.role == MessageRole.COMPACTION), ""
        ),
    }
    out_path = ROOT / "test" / "results" / f"compact_append_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"结果: {out_path}")

    if n_comp < 3:
        print(f"FAIL: compaction 次数 {n_comp} < 3")
        return 2
    if not log_path.exists() or legacy_tr.exists() or legacy_sj.exists():
        print("FAIL: 文件布局不符合 session.jsonl / 无旧 session.json·transcript.jsonl")
        return 2
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
