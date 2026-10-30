"""Command line client for the Niural support agent server.

    uv run python main.py                       # chat with the agent (same as: main.py chat)
    uv run python main.py chat --log session.jsonl
    uv run python main.py audit                 # review the auditor's verdicts on finished conversations
    uv run python main.py --url http://localhost:9090 chat

chat: type a question. After each answer it prints what the agent did: how the router routed the question, every tool
call with its arguments and the API call it made, and the sources. Commands: /new, /quit.

audit: the human in the loop. Lists the auditor's verdicts (score, how the conversation ended, issues, suggested
improvements). You approve or reject the suggestions; nothing is changed automatically.
"""
import argparse
import json
import os
import sys
import time

import httpx

DIM, BOLD, RESET = ("\033[2m", "\033[1m", "\033[0m") if sys.stdout.isatty() else ("", "", "")


# ---------------------------------------------------------------- chat

def show_trace(question: str, data: dict) -> None:
    print(f"{DIM}  route: {data['route']}")
    for q in data["queries"]:
        if q["query"].strip() != question.strip():  # only worth showing when the router changed the question
            print(f"  {q['agent']} agent was asked: {q['query']}")
    for number, call in enumerate(data["tool_calls"], start=1):
        outcome = "ok" if call["ok"] else "FAILED"
        print(f"  tool call {number}: {call['tool']}({json.dumps(call['arguments'])})")
        print(f"      -> {call['endpoint'] or 'rejected before calling the API'}  [{outcome}]")
    if not data["tool_calls"]:
        print("  tool calls: none")
    t = data.get("timings_ms") or {}
    print(f"  time: {t.get('total', 0) / 1000:.1f}s (router {t.get('router', 0) / 1000:.1f}s, "
          f"agents {t.get('agents', 0) / 1000:.1f}s)")
    print(RESET, end="")


def begin(client: httpx.Client) -> str:
    convo_id = client.post("/conversations").json()["conversation_id"]
    print(f"{DIM}conversation {convo_id}{RESET}")
    return convo_id


def close(client: httpx.Client, convo_id: str) -> None:
    try:
        client.delete(f"/conversations/{convo_id}")  # also triggers the audit
    except httpx.HTTPError:
        pass  # the server is gone or the conversation already ended; nothing to clean up


def chat(client: httpx.Client, args: argparse.Namespace) -> None:
    convo_id = begin(client)
    print("Ask a question. /new starts a new conversation, /quit exits.\n")
    try:
        while True:
            try:
                question = input(f"{BOLD}you>{RESET} ").strip()
            except EOFError:
                break
            if not question:
                continue
            if question == "/quit":
                break
            if question == "/new":
                close(client, convo_id)
                convo_id = begin(client)
                continue

            response = client.post(f"/conversations/{convo_id}/messages", json={"message": question})
            if response.status_code == 404:
                print("That conversation has ended. Starting a new one.")
                convo_id = begin(client)
                continue
            if response.status_code != 200:
                print(f"error {response.status_code}: {response.text}")
                continue

            data = response.json()
            show_trace(question, data)
            print(f"{BOLD}agent>{RESET} {data['reply']}\n")

            if args.log:
                with open(args.log, "a", encoding="utf-8") as log:
                    log.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "conversation_id": convo_id,
                                          "question": question, **data}) + "\n")
            if data["status"] != "active":
                print(f"{DIM}Conversation {data['status']}. Starting a new one.{RESET}")
                convo_id = begin(client)
    except KeyboardInterrupt:
        print()
    finally:
        close(client, convo_id)
        print(f"{DIM}The auditor reviews finished conversations in the background. Run: main.py audit{RESET}")


# ---------------------------------------------------------------- audit

def show_audit_list(client: httpx.Client, review: str | None) -> None:
    audits = client.get("/audits", params={"review": review} if review else {}).json()
    if not audits:
        print("No audits yet. They appear a few seconds after a conversation ends." if review == "pending"
              else "No audits.")
        return
    for a in audits:
        flag = "ended well" if a["ended_well"] else "ended badly"
        print(f"#{a['id']:<3} {a['score']}/5  {flag:11}  {a['outcome']:24} {a['review']:9} {a['title'][:55]!r}")


def show_audit(client: httpx.Client, audit_id: int) -> None:
    response = client.get(f"/audits/{audit_id}")
    if response.status_code == 404:
        print("No such audit.")
        return
    audit = response.json()
    print(f"\n{BOLD}Audit #{audit['id']}{RESET}  conversation {audit['conversation_id']}  ended by {audit['ended_by']}")
    for number, trace in enumerate(audit["record"]["traces"], start=1):
        print(f"\n  turn {number}  customer: {trace['query']}")
        print(f"{DIM}    route: {trace['route']}")
        for call in trace.get("tool_calls", []):
            print(f"    tool call: {call['tool']}({call['arguments']}) -> {call['endpoint']} [{'ok' if call['ok'] else 'FAILED'}]")
        print(f"    sources: {trace['sources'] or 'none'}{RESET}")
        print(f"    agent: {trace['answer'][:400]}{'...' if len(trace['answer']) > 400 else ''}")
    print(f"\n{BOLD}Verdict{RESET}  score {audit['score']}/5, "
          f"{'ended on a good note' if audit['ended_well'] else 'did NOT end on a good note'}, outcome: {audit['outcome']}")
    print(f"  {audit['reasons']}")
    for issue in audit["issues"]:
        print(f"  issue (turn {issue['turn']}): {issue['problem']}")
    for number, suggestion in enumerate(audit["suggestions"], start=1):
        print(f"  suggestion {number}: {suggestion}")
    print(f"  review: {audit['review']} {audit['review_note']}\n")


def audit(client: httpx.Client, args: argparse.Namespace) -> None:
    print("Audit review (human in the loop). Commands: list, all, show <id>, approve <id> [note], "
          "reject <id> [note], quit\n")
    show_audit_list(client, "pending")
    while True:
        try:
            parts = input(f"{BOLD}audit>{RESET} ").strip().split(maxsplit=2)
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not parts:
            continue
        command, rest = parts[0], parts[1:]
        if command in ("quit", "exit", "q"):
            return
        if command == "list":
            show_audit_list(client, "pending")
        elif command == "all":
            show_audit_list(client, None)
        elif command == "show" and rest and rest[0].isdigit():
            show_audit(client, int(rest[0]))
        elif command in ("approve", "reject") and rest and rest[0].isdigit():
            decision = "approved" if command == "approve" else "rejected"
            note = rest[1] if len(rest) > 1 else ""
            response = client.post(f"/audits/{rest[0]}/review", json={"decision": decision, "note": note})
            print(f"audit #{rest[0]} {decision}" if response.status_code == 200 else "No such audit.")
        else:
            print("Commands: list, all, show <id>, approve <id> [note], reject <id> [note], quit")


# ---------------------------------------------------------------- entry point

def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with the Niural support agent, or review its audits.")
    parser.add_argument("--url", default=os.environ.get("NIURAL_URL", "http://localhost:9090"), help="server address")
    commands = parser.add_subparsers(dest="command")
    chat_parser = commands.add_parser("chat", help="talk to the agent (default)")
    chat_parser.add_argument("--log", help="append every turn (question, reply, route, tool calls) to this JSONL file")
    commands.add_parser("audit", help="review the auditor's verdicts on finished conversations")
    args = parser.parse_args()
    args.log = getattr(args, "log", None)

    client = httpx.Client(base_url=args.url, timeout=120)
    try:
        client.get("/health").raise_for_status()
    except httpx.HTTPError as error:
        sys.exit(f"The server at {args.url} is not ready: {error}\nStart it with: docker compose up")

    (audit if args.command == "audit" else chat)(client, args)


if __name__ == "__main__":
    main()