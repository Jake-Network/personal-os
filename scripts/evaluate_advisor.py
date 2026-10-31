"""Golden-set evaluation with the provider selected in the app (ChatGPT, a local model, ...).

Runs every case in tests/fixtures/advisor_golden/golden.json through the advisor, checks
what was sent (same checks as the CI test) and what was answered, and writes a Markdown
report. Synthetic personas only. Each case reseeds the persona tables, so this refuses any
database whose name does not end in `_eval`.

Setup once: start the backend on the `_eval` database, connect the AI provider and confirm
the transfer policy in Settings, then stop it and run:

    DATABASE_URL=postgresql+psycopg://u:p@127.0.0.1:5432/personal_os_eval \\
    uv run python scripts/evaluate_advisor.py --out docs/evaluations/advisor-<model>-<date>.md

Every case calls the model; the report records model calls, latency and failures.
"""
import argparse
import asyncio
import json
import os
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, help="Markdown report path (default: print)")
    parser.add_argument("--case", action="append", help="Run only these case IDs")
    args = parser.parse_args()
    name = urlsplit(os.environ.get("DATABASE_URL", "")).path.rsplit("/", 1)[-1]
    if not name.endswith("_eval"):
        sys.exit("evaluate_advisor: DATABASE_URL must name a disposable database ending in '_eval'")

    from advisor_golden import answer_problems, load, seed, sent_problems
    from app.config import settings
    from app.enums.context_category import Category
    from app.modules.advisor.advisor_manager import advisor_manager
    from app.modules.advisor.types import AskOptions
    from app.modules.database import db
    from app.modules.finance.clock import local_today
    from app.modules.llm import llm_gateway_manager as gateway_module
    from app.modules.llm.llm_gateway_manager import llm_gateway_manager

    db.init(settings.resolved_database_url)
    golden = load()
    cases = [c for c in golden["questions"] if not args.case or c["id"] in args.case]
    sent_requests = []
    original_stream = gateway_module.LLMGatewayManager.stream

    async def recording_stream(self, session, request, conversation_id=None):
        sent_requests.append(request)
        async for event in original_stream(self, session, request, conversation_id):
            yield event

    gateway_module.LLMGatewayManager.stream = recording_stream
    rows, provider, model = [], None, None
    with db.session() as session:
        provider = llm_gateway_manager.provider_name(session)
        for case in cases:
            seed(session, golden["personas"][case["persona"]], local_today())
            conversation = advisor_manager.create_conversation(session, f"eval {case['id']}")
            options = AskOptions(exclude=frozenset(Category(c) for c in case["exclude"])) if case.get("exclude") else None
            before, started, answer, error = len(sent_requests), time.monotonic(), "", None

            async def collect():
                return [event async for event in advisor_manager.ask(session, conversation, case["question"], options)]

            try:
                events = asyncio.run(collect())
                done = events[-1]
                if done.get("type") != "done":
                    error = done.get("message") or done.get("code") or "no done event"
                answer = done.get("answer") or "".join(e.get("text", "") for e in events if e.get("type") == "delta")
            except Exception as exc:  # noqa: BLE001 - the report records every failure kind
                error = f"{type(exc).__name__}: {exc}"
            requests = sent_requests[before:]
            model = model or (requests[-1].model if requests else None)
            problems = [f"error: {error}"] if error else []
            if requests:
                developer = next((item["content"] for item in requests[-1].input if item["role"] == "developer"
                                  and str(item["content"]).startswith("Context Package")), None)
                package = json.loads(developer.split("\n", 1)[1]) if developer else {}
                problems += sent_problems(case, package, json.dumps([r.input for r in requests], ensure_ascii=False))
            problems += answer_problems(case, answer)
            rows.append({"id": case["id"], "ok": not problems, "problems": problems, "calls": len(requests),
                         "seconds": round(time.monotonic() - started, 1), "answer": answer})

    passed = sum(r["ok"] for r in rows)
    lines = [f"# 상담 golden-set 평가 — {model or provider} — {date.today().isoformat()}", "",
             f"- 제공자: `{provider}`, 모델: `{model}`", f"- 통과: **{passed}/{len(rows)}**",
             "- 합성 페르소나만 사용했다. 통과는 고정 기준(전송 범위·필수 수치·고지 문구)의 충족이며 답변 품질 전반의 보증이 아니다.", "",
             "| 사례 | 결과 | 모델 호출 | 시간(초) | 문제 |", "|---|---|---:|---:|---|"]
    lines += [f"| {r['id']} | {'통과' if r['ok'] else '실패'} | {r['calls']} | {r['seconds']} | {'; '.join(r['problems']) or '—'} |"
              for r in rows]
    lines += ["", "## 답변", ""]
    for r in rows:
        lines += [f"### {r['id']}", "", r["answer"].strip() or "(답변 없음)", ""]
    report = "\n".join(lines)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"{passed}/{len(rows)} passed → {args.out}")
    else:
        print(report)
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
