"""Collect designated packets from saved native read_thread pages. Never executes tasks.

The calling operator must fetch pages through authenticated native tools, in newest-first
cursor order. Supplied JSON is not authentication. Candidates require envelope/hash
validation and human authority before ledger processing or effects.
Native pages and turns are newest-first; items within a turn are oldest-first.
The operator must verify these ordering assumptions against the actual API.
"""
import argparse, json, pathlib, sys
MARKER = "AZ_BRIDGE_V1 "

def require_shape(value, expected, label):
    if not isinstance(value, expected):
        raise ValueError('invalid native shape: '+label)
    return value

def output_text(item, turn):
    if (item.get("type") == "mcpToolCall" and item.get("server") == "codex_apps"
        and item.get("tool") == "user_message.send_message" and item.get("status") == "completed"):
        return require_shape(item.get("arguments", {}), dict, 'arguments').get("text")
    if item.get("type") in ("agentMessage", "assistantMessage") and turn.get("status") == "completed":
        return item.get("text")
    return None

def scan_pages(pages, expected_source, boundary, page_limit=6):
    if not expected_source or not boundary or not 1 <= page_limit <= 6:
        raise ValueError("registered source, established boundary and page limit 1..6 required")
    require_shape(pages, list, 'pages')
    candidates=[]; issues=[]; seen=set(); found=False; newest=None; continuation=None; used=0
    expected_cursor=None
    for page in pages[:page_limit]:
        used += 1
        require_shape(page, dict, 'page')
        if 'requestedCursor' not in page:
            issues.append('missing acquisition cursor annotation')
        if page.get('requestedCursor') != expected_cursor:
            issues.append('cursor chain gap'); break
        if require_shape(page.get("thread", {}), dict, 'thread').get("id") != expected_source:
            raise ValueError("wrong registered source thread")
        meta=require_shape(page.get("page", {}), dict, 'page metadata')
        if meta.get("order") != "newest_first": raise ValueError("unexpected page order")
        continuation=meta.get("nextCursor")
        if 'turns' not in page: issues.append('missing required turns container')
        if not isinstance(meta.get('hasMore'), bool): issues.append('missing or invalid hasMore')
        for turn in require_shape(page.get("turns", []), list, 'turns'):
            require_shape(turn, dict, 'turn')
            if 'items' not in turn: issues.append('missing required items container')
            for item in reversed(require_shape(turn.get("items", []), list, 'items')):
                require_shape(item, dict, 'item')
                identifier=item.get("id")
                if not isinstance(identifier,str) or not identifier:
                    issues.append("item missing stable identifier"); continue
                if newest is None: newest=identifier
                if identifier == boundary: found=True; break
                if identifier in seen: continue
                seen.add(identifier)
                kind=item.get('type')
                if not isinstance(kind,str) or not kind:
                    issues.append('missing or invalid item type: '+identifier); continue
                if kind=='mcpToolCall' and any(not isinstance(item.get(field),str) or not item[field]
                                              for field in ('server','tool')):
                    issues.append('missing or invalid tool classification: '+identifier); continue
                if (item.get('type') in ('agentMessage','assistantMessage')
                    and turn.get('status') != 'completed'):
                    issues.append('unfinished assistant output: '+identifier); continue
                if (item.get('type') == 'mcpToolCall' and item.get('server') == 'codex_apps'
                    and item.get('tool') == 'user_message.send_message' and item.get('status') != 'completed'):
                    issues.append('unfinished source output: '+identifier); continue
                source_output = (item.get('type') in ('agentMessage','assistantMessage') or
                    (item.get('type') == 'mcpToolCall' and item.get('server') == 'codex_apps'
                     and item.get('tool') == 'user_message.send_message'))
                if source_output and (item.get("truncated") or item.get("argumentsTruncated")):
                    issues.append("truncated source output: "+identifier); continue
                text=output_text(item,turn)
                if source_output and not isinstance(text,str):
                    issues.append('missing or invalid source text: '+identifier); continue
                if not isinstance(text,str) or not text.startswith(MARKER): continue
                try:
                    packet=json.loads(text[len(MARKER):])
                    if not isinstance(packet,dict): raise ValueError("envelope is not an object")
                except (ValueError,json.JSONDecodeError):
                    issues.append("incomplete or invalid designated packet: "+identifier); continue
                candidates.append({"source_thread_id":expected_source,"source_item_id":identifier,
                                   "turn_id":turn.get("id"),"packet":packet})
            if found: break
        if found: break
        if not meta.get("hasMore"): break
        if not continuation: issues.append("missing older-page cursor"); break
        expected_cursor=continuation
    if not found: issues.append("known source-item boundary not reached")
    candidates.reverse()
    complete=found and not issues
    return {"complete_coverage":complete,"boundary":boundary,"initial_newest":newest,
            "continuation":None if complete else continuation,"pages":used,
            "candidates":candidates,"issues":issues}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages",required=True,help="JSON array of authenticated read_thread page objects")
    parser.add_argument("--source",required=True);parser.add_argument("--boundary",required=True)
    a=parser.parse_args()
    try:
        result=scan_pages(json.loads(pathlib.Path(a.pages).read_text(encoding="utf-8")),a.source,a.boundary)
    except (OSError, ValueError) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr)
        return 1
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['complete_coverage'] else 3

if __name__ == "__main__": sys.exit(main())
