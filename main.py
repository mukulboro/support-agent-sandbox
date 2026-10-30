"""Command line client for the Niural support agent server.

    uv run python main.py                                   # talks to http://localhost:9090
    uv run python main.py --url http://localhost:9090 --log session.jsonl

Type a question and press enter. After each answer it prints what the agent did: how the router routed the question,
every tool call with its arguments and the API call it made, and the sources. Commands: /new, /quit.
"""
import argparse
import json
import os
import sys
import time

import httpx

DIM, BOLD, RESET = ("\033[2m", "\033[1m", "\033[0m") if sys.stdout.isatty() else ("", "", "")


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
    print(RESET, end="")


def begin(client: httpx.Client) -> str:
    convo_id = client.post("/conversations").json()["conversation_id"]
    print(f"{DIM}conversation {convo_id}{RESET}")
    return convo_id


def close(client: httpx.Client, convo_id: str) -> None:
    try:
        client.delete(f"/conversations/{convo_id}")
    except httpx.HTTPError:
        pass  # the server is gone or the conversation already ended; nothing to clean up


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with the Niural support agent.")
    parser.add_argument("--url", default=os.environ.get("NIURAL_URL", "http://localhost:9090"), help="server address")
    parser.add_argument("--log", help="append every turn (question, reply, route, tool calls) to this JSONL file")
    args = parser.parse_args()

    client = httpx.Client(base_url=args.url, timeout=120)
    try:
        client.get("/health").raise_for_status()
    except httpx.HTTPError as error:
        sys.exit(f"The server at {args.url} is not ready: {error}\nStart it with: docker compose up")

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


if __name__ == "__main__":
    main()
