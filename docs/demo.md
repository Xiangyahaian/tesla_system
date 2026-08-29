# Demo walkthrough (~3–4 minutes)

Entry: `python run.py` → http://127.0.0.1:6006  
(Build frontend first: `cd frontend && npm run build`)

## Opening

Show the cabin shell: Drive / Apps / Agent navigation, status strip, voice orb, live vehicle state. Emphasize Gateway tool calls, Policy confirmation, and observable transcripts—not a chat wrapper.

## 1 · Multi-tool

`打开空调并播放周杰伦的晴天`

Expect: multi-tool plan, Climate / Media HUD updates, turn rail in the conversation.

## 2 · State + anaphora

`现在音量多少` → `小一点`

Expect: read-then-write on volume; status strip / HUD stay in sync.

## 3 · Safety gate

`打开后备箱` → confirm card → confirm.

Expect: high-risk actions go through Policy, not free-form model text.

## 4 · Apps + RAG

Open an app on **Apps**, return to Drive, ask `自动泊车怎么用`.

Expect: foreground app sync; retrieved handbook snippets with citations.

## Close

On **Agent**: turn list, model I/O, compact. On **Settings**: tool registry.

Gateway is stubbed and swappable; the frontend is a multi-route cabin shell, not a single HTML page.
