"""Supermemory enforcement hook for Hermes gateway.

Fires on:
  agent:start  -- extract entities from message, search Supermemory, write
                   briefing file, inject pointer into MEMORY.md
  agent:end    -- extract facts/decisions from latest exchange via cheap LLM,
                   save to Supermemory (debounced)
  session:end  -- full session summary via cheap LLM, save to Supermemory

Architecture:
  - MEMORY.md is re-read every message (fresh AIAgent per turn)
  - agent:start is awaited before the agent runs
  - Hook writes a one-line pointer to MEMORY.md; actual context lives in
    ~/.hermes/supermemory_briefing.md
  - No gateway code modifications required
"""

import fcntl
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HERMES_HOME = Path(os.getenv("HERMES_HOME", Path.home() / ".hermes"))
MEMORY_DIR = HERMES_HOME / "memories"
MEMORY_FILE = MEMORY_DIR / "MEMORY.md"
BRIEFING_FILE = HERMES_HOME / "supermemory_briefing.md"
STATE_FILE = Path(__file__).parent / "state.json"
ENTITY_REGISTRY = Path(__file__).parent / "entities.json"
SESSIONS_DIR = HERMES_HOME / "sessions"
STATE_DB = HERMES_HOME / "state.db"
MEMORY_SCRIPT = HERMES_HOME / "skills" / "productivity" / "supermemory" / "scripts" / "memory.py"
DOTENV_PATH = HERMES_HOME / ".env"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CONTAINER = "hermes"
DEBOUNCE_SECONDS = 300  # 5 minutes
DECISION_KEYWORDS = [
    "let's go with", "approved", "i want", "decision:", "we'll do",
    "go ahead", "ship it", "confirmed", "let's use", "the plan is",
    "remember this", "don't forget",
]
# Extraction model -- cheap and fast
EXTRACT_MODEL = "google/gemini-2.5-flash-lite"
EXTRACT_MAX_TOKENS = 512

# Marker line in MEMORY.md
MEMORY_MARKER = "[Supermemory] Context pre-loaded to ~/.hermes/supermemory_briefing.md -- read if the topic is relevant."

ENTRY_DELIMITER = "\n§\n"

# Entity registry -- seeded from Supermemory, updated by agent:end
# In-memory cache (lives for the gateway process lifetime)
_entity_cache = None          # dict: lowercase_key -> canonical_name
_entity_cache_time = 0        # timestamp of last load
ENTITY_CACHE_TTL = 3600       # refresh from disk every hour
ENTITY_SEED_LIMIT = 100       # how many SM docs to scan when seeding

# ---------------------------------------------------------------------------
# Environment loading
# ---------------------------------------------------------------------------
_env_loaded = False

def _ensure_env():
    """Load .env if keys aren't already in environment."""
    global _env_loaded
    if _env_loaded:
        return
    _env_loaded = True
    if os.environ.get("SUPERMEMORY_API_KEY") and os.environ.get("OPENROUTER_API_KEY"):
        return
    if DOTENV_PATH.is_file():
        with open(DOTENV_PATH) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and not os.environ.get(k):
                        os.environ[k] = v


# ---------------------------------------------------------------------------
# Supermemory API (direct HTTP, no subprocess)
# ---------------------------------------------------------------------------
SM_BASE = "https://api.supermemory.ai"

def _sm_api(method, path, body=None):
    """Call Supermemory API directly."""
    _ensure_env()
    api_key = os.environ.get("SUPERMEMORY_API_KEY", "")
    if not api_key:
        print("[superbud-memory] SUPERMEMORY_API_KEY not set", flush=True)
        return {}
    url = f"{SM_BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "supermemory-hook/1.0",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except Exception as e:
        print(f"[superbud-memory] API error: {e}", flush=True)
        return {}


def _sm_search(query, limit=5):
    """Search Supermemory, return list of result dicts."""
    result = _sm_api("POST", "/v3/search", {
        "q": query,
        "containerTags": [CONTAINER],
    })
    return result.get("results", [])[:limit]


def _sm_save(content, tags=""):
    """Save content to Supermemory."""
    body = {"content": content, "containerTag": CONTAINER}
    if tags:
        body["metadata"] = {"tags": tags}
    return _sm_api("POST", "/v3/documents", body)


# ---------------------------------------------------------------------------
# OpenRouter API (for extraction)
# ---------------------------------------------------------------------------
OR_BASE = "https://openrouter.ai/api/v1"

def _call_llm(system_prompt, user_prompt, max_tokens=EXTRACT_MAX_TOKENS):
    """Call a cheap LLM via OpenRouter for fact extraction."""
    _ensure_env()
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        print("[superbud-memory] OPENROUTER_API_KEY not set", flush=True)
        return ""

    body = {
        "model": EXTRACT_MODEL,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{OR_BASE}/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://hermes.agent",
            "X-Title": "Hermes Supermemory Hook",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        print(f"[superbud-memory] LLM call error: {e}", flush=True)
        return ""


# ---------------------------------------------------------------------------
# Entity registry -- known names cached for case-insensitive matching
# ---------------------------------------------------------------------------

def _load_entity_registry():
    """Load the entity registry from disk, seeding from Supermemory if needed."""
    global _entity_cache, _entity_cache_time

    now = time.time()

    # Return cached version if fresh
    if _entity_cache is not None and (now - _entity_cache_time) < ENTITY_CACHE_TTL:
        return _entity_cache

    # Load from disk
    registry = {}
    if ENTITY_REGISTRY.exists():
        try:
            registry = json.loads(ENTITY_REGISTRY.read_text(encoding="utf-8"))
        except Exception:
            registry = {}

    # Seed from Supermemory if registry is empty or very small
    if len(registry) < 10:
        registry = _seed_entity_registry(registry)

    _entity_cache = registry
    _entity_cache_time = now
    return registry


def _seed_entity_registry(existing):
    """Seed the entity registry by scanning recent Supermemory documents."""
    _ensure_env()
    registry = dict(existing)

    # Pull recent documents via search with targeted queries
    seed_queries = [
        "Superbud client deal company",
        "Jordan Stella Superbud",
        "cannabis dispensary brand",
        "SOW project proposal contract",
        "Linear Attio Fireflies integration",
        "Proper Lion Labs Cali",
    ]

    all_content = []
    for q in seed_queries:
        results = _sm_search(q, limit=15)
        for r in results:
            chunks = r.get("chunks", [])
            if chunks:
                all_content.append(chunks[0].get("content", ""))

    # Extract entity-like names from all retrieved content
    for content in all_content:
        names = _regex_extract_entities(content)
        for name in names:
            _register_entity(registry, name)

    # Also seed from MEMORY.md (rich source of known entities)
    if MEMORY_FILE.exists():
        try:
            mem_content = MEMORY_FILE.read_text(encoding="utf-8")
            for name in _regex_extract_entities(mem_content):
                _register_entity(registry, name)
        except Exception:
            pass

    # Also seed from USER.md
    user_file = MEMORY_DIR / "USER.md"
    if user_file.exists():
        try:
            user_content = user_file.read_text(encoding="utf-8")
            for name in _regex_extract_entities(user_content):
                _register_entity(registry, name)
        except Exception:
            pass

    _save_entity_registry(registry)
    print(f"[superbud-memory] Entity registry seeded with {len(registry)} entries", flush=True)
    return registry


def _register_entity(registry, canonical_name):
    """Add an entity to the registry with all useful lookup keys."""
    if not canonical_name or len(canonical_name) < 2:
        return

    # Full name as key
    registry[canonical_name.lower()] = canonical_name

    # Individual words (3+ chars) as keys pointing to full name
    words = canonical_name.split()
    if len(words) > 1:
        for word in words:
            w_lower = word.lower()
            # Only register individual words that are distinctive (4+ chars,
            # not common English words)
            if len(w_lower) >= 4 and w_lower not in _COMMON_WORDS:
                # Don't overwrite a more specific entry with a less specific one
                if w_lower not in registry:
                    registry[w_lower] = canonical_name


def _save_entity_registry(registry):
    """Persist the entity registry to disk."""
    try:
        ENTITY_REGISTRY.write_text(
            json.dumps(registry, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[superbud-memory] Failed to save entity registry: {e}", flush=True)


def _add_entities_to_registry(names):
    """Add new entity names to the registry (called from agent:end)."""
    global _entity_cache
    registry = _load_entity_registry()
    changed = False
    for name in names:
        if name.lower() not in registry:
            _register_entity(registry, name)
            changed = True
    if changed:
        _entity_cache = registry
        _save_entity_registry(registry)


# Common English words to exclude from single-word entity matching.
# These would cause false positives when matching message text.
_COMMON_WORDS = frozenset([
    "about", "after", "again", "also", "back", "been", "before", "being",
    "between", "both", "came", "come", "could", "does", "done", "down",
    "each", "even", "every", "find", "first", "from", "give", "going",
    "good", "great", "have", "help", "here", "high", "into", "just",
    "keep", "know", "last", "left", "like", "line", "long", "look",
    "made", "make", "many", "might", "more", "most", "much", "must",
    "name", "need", "never", "next", "only", "open", "other", "over",
    "part", "plan", "play", "point", "pull", "push", "really", "right",
    "said", "same", "send", "should", "show", "side", "since", "some",
    "still", "such", "sure", "take", "tell", "than", "that", "them",
    "then", "there", "these", "they", "thing", "think", "this", "those",
    "time", "turn", "under", "upon", "very", "want", "well", "were",
    "what", "when", "where", "which", "while", "will", "with", "work",
    "would", "year", "your", "build", "built", "call", "check", "create",
    "data", "file", "hook", "list", "load", "move", "note", "read",
    "real", "rest", "rule", "save", "search", "session", "start", "state",
    "stop", "test", "tool", "type", "update", "used", "using", "write",
    "agent", "memory", "system", "model", "prompt", "response", "message",
    "context", "content", "config", "setup", "handle", "process",
    "already", "getting", "looking", "running", "working", "trying",
    "something", "anything", "everything", "nothing",
    # Domain-generic words that appear capitalized in notes but aren't entities
    "always", "never", "true", "false", "free", "core", "direct", "depth",
    "focus", "format", "nature", "personal", "recurring", "revenue", "root",
    "saving", "managed", "services", "accounts", "issues", "projects", "order",
    "dogs", "wife", "founder", "interests", "expects", "makes", "remind",
    "lowercase", "company", "digital", "fire",
])


# ---------------------------------------------------------------------------
# Entity extraction
# ---------------------------------------------------------------------------

def _regex_extract_entities(text):
    """Regex-based entity extraction. Used for seeding and as a fallback.

    Returns a list of canonical entity names (properly cased).
    """
    if not text:
        return []

    entities = set()

    # Capitalized multi-word names (e.g., "Proper Cannabis", "Jordan Stella")
    for m in re.finditer(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b', text):
        name = m.group(1)
        if name.split()[0] not in ("The", "This", "That", "Here", "There", "What",
                                    "When", "Where", "How", "Why", "Which", "Please",
                                    "Could", "Would", "Should", "Can", "Will", "Does",
                                    "Did", "Has", "Have", "Had", "Let", "Just"):
            entities.add(name)

    # Single capitalized words that might be names/companies (4+ chars,
    # not at sentence start)
    for m in re.finditer(r'(?<=[a-z.,;:!?]\s)([A-Z][a-z]{3,})\b', text):
        word = m.group(1)
        if word.lower() not in _COMMON_WORDS:
            entities.add(word)

    # Name=role or Name(role) patterns common in notes
    # e.g., "Cardell=champion" or "Tyson(CFO)"
    for m in re.finditer(r'\b([A-Z][a-z]+)\s*[=(]', text):
        entities.add(m.group(1))

    # Names after key prepositions: "with Cardell", "from Kelly", "to Jordan"
    for m in re.finditer(r'\b(?:with|from|to|for|by|via|ask|tell|contact|ping|email)\s+([A-Z][a-z]+)\b', text):
        word = m.group(1)
        if word.lower() not in _COMMON_WORDS:
            entities.add(word)

    # @mentions
    for m in re.finditer(r'@(\w+)', text):
        entities.add(m.group(1))

    # Project codes like GROW-1274 (case-insensitive)
    for m in re.finditer(r'\b([A-Za-z]+-\d+)\b', text):
        entities.add(m.group(1).upper())

    return list(entities)


def _extract_entities(text):
    """Extract entity names from message text using registry + regex fallback.

    Case-insensitive. Handles lowercase, TTS, and quick-typed input.
    Returns a list of canonical search queries.
    """
    if not text:
        return []

    registry = _load_entity_registry()
    entities = {}  # canonical_name -> True (using dict to preserve insertion order)

    # --- Phase 1: Registry matching (case-insensitive) ---
    # Tokenize the message into words and multi-word phrases
    text_lower = text.lower()
    words = re.findall(r'[a-z0-9]+(?:[-\'][a-z0-9]+)*', text_lower)

    # Check bigrams and trigrams first (longer matches are more specific)
    for n in (3, 2):
        for i in range(len(words) - n + 1):
            phrase = " ".join(words[i:i + n])
            if phrase in registry:
                entities[registry[phrase]] = True

    # Check individual words
    for word in words:
        if len(word) >= 3 and word in registry:
            canonical = registry[word]
            if canonical not in entities:
                entities[canonical] = True

    # --- Phase 2: Project codes (case-insensitive) ---
    for m in re.finditer(r'\b([a-zA-Z]+-\d+)\b', text):
        code = m.group(1).upper()
        if code not in entities:
            entities[code] = True

    # --- Phase 3: @mentions ---
    for m in re.finditer(r'@(\w+)', text):
        mention = m.group(1)
        if mention not in entities:
            entities[mention] = True

    # --- Phase 4: Regex fallback for any properly cased entities ---
    # (catches new names the user happens to capitalize)
    for name in _regex_extract_entities(text):
        if name not in entities:
            entities[name] = True

    return list(entities.keys())[:8]


# ---------------------------------------------------------------------------
# MEMORY.md safe editing (respects file lock protocol)
# ---------------------------------------------------------------------------

def _inject_memory_pointer():
    """Add the [Supermemory] marker line to the top of MEMORY.md."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = MEMORY_FILE.with_suffix(MEMORY_FILE.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    fd = open(lock_path, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)

        # Read current content
        content = ""
        if MEMORY_FILE.exists():
            content = MEMORY_FILE.read_text(encoding="utf-8")

        # Remove existing marker if present
        content = _strip_marker(content)

        # Prepend marker
        new_content = MEMORY_MARKER + ENTRY_DELIMITER + content

        # Atomic write via temp file + rename
        tmp = tempfile.NamedTemporaryFile(
            mode="w", dir=MEMORY_DIR, suffix=".tmp", delete=False,
            encoding="utf-8",
        )
        try:
            tmp.write(new_content)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp.close()
            os.replace(tmp.name, MEMORY_FILE)
        except Exception:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            raise
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()


def _remove_memory_pointer():
    """Remove the [Supermemory] marker from MEMORY.md."""
    if not MEMORY_FILE.exists():
        return

    lock_path = MEMORY_FILE.with_suffix(MEMORY_FILE.suffix + ".lock")
    fd = open(lock_path, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        content = MEMORY_FILE.read_text(encoding="utf-8")
        cleaned = _strip_marker(content)
        if cleaned != content:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", dir=MEMORY_DIR, suffix=".tmp", delete=False,
                encoding="utf-8",
            )
            try:
                tmp.write(cleaned)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp.close()
                os.replace(tmp.name, MEMORY_FILE)
            except Exception:
                tmp.close()
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
                raise
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()


def _strip_marker(content):
    """Remove the [Supermemory] marker entry from content."""
    # The marker is a full entry delimited by §
    marker_entry = MEMORY_MARKER + ENTRY_DELIMITER
    content = content.replace(marker_entry, "")
    # Also handle case where marker is the only/last entry (no trailing delimiter)
    content = content.replace(MEMORY_MARKER, "")
    # Clean up any double delimiters left behind
    while ENTRY_DELIMITER + ENTRY_DELIMITER in content:
        content = content.replace(ENTRY_DELIMITER + ENTRY_DELIMITER, ENTRY_DELIMITER)
    # Strip leading/trailing delimiter
    content = content.strip("\n§ ")
    if content and not content.endswith("\n"):
        content += "\n"
    return content


# ---------------------------------------------------------------------------
# Briefing file
# ---------------------------------------------------------------------------

def _write_briefing(results_by_entity):
    """Write the Supermemory briefing file."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# Supermemory Context (auto-generated)",
        f"Updated: {now}",
        "",
        "## Relevant past context",
        "",
    ]

    for entity, results in results_by_entity.items():
        lines.append(f"### {entity}")
        for r in results:
            chunks = r.get("chunks", [])
            content = chunks[0].get("content", "")[:300] if chunks else ""
            created = r.get("createdAt", "")[:10]
            if content:
                # Clean up content for readability
                content = content.replace("\n", " ").strip()
                lines.append(f"- {content}")
                if created:
                    lines.append(f"  (saved: {created})")
        lines.append("")

    BRIEFING_FILE.write_text("\n".join(lines), encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Transcript reading
# ---------------------------------------------------------------------------

def _read_recent_transcript(session_id, last_n=6):
    """Read the last N user/assistant messages from the session.

    Tries SQLite first, falls back to JSONL.
    Returns list of {role, content} dicts.
    """
    messages = []

    # Try SQLite
    if STATE_DB.exists():
        try:
            conn = sqlite3.connect(str(STATE_DB), timeout=5)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT role, content FROM messages "
                "WHERE session_id = ? AND role IN ('user', 'assistant') AND content IS NOT NULL "
                "ORDER BY timestamp DESC, id DESC LIMIT ?",
                (session_id, last_n),
            )
            rows = cursor.fetchall()
            conn.close()
            if rows:
                messages = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
                return messages
        except Exception as e:
            print(f"[superbud-memory] SQLite read failed: {e}", flush=True)

    # Fall back to JSONL
    jsonl_path = SESSIONS_DIR / f"{session_id}.jsonl"
    if jsonl_path.exists():
        try:
            all_msgs = []
            with open(jsonl_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        if msg.get("role") in ("user", "assistant") and msg.get("content"):
                            all_msgs.append({"role": msg["role"], "content": msg["content"]})
                    except json.JSONDecodeError:
                        continue
            messages = all_msgs[-last_n:]
        except Exception as e:
            print(f"[superbud-memory] JSONL read failed: {e}", flush=True)

    return messages


def _read_full_transcript(session_id):
    """Read entire user/assistant transcript for session summary."""
    return _read_recent_transcript(session_id, last_n=9999)


# ---------------------------------------------------------------------------
# Debounce
# ---------------------------------------------------------------------------

def _load_state():
    """Load debounce state from disk."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_save": {}}


def _save_state(state):
    """Persist debounce state."""
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _should_debounce(session_id, message=""):
    """Check if we should skip extraction for this session.

    Returns False (don't debounce) if:
    - First time seeing this session
    - More than DEBOUNCE_SECONDS since last save
    - Message contains decision keywords
    """
    # Decision keywords always bypass debounce
    msg_lower = message.lower()
    for kw in DECISION_KEYWORDS:
        if kw in msg_lower:
            return False

    state = _load_state()
    last = state.get("last_save", {}).get(session_id)
    if not last:
        return False

    try:
        elapsed = time.time() - float(last)
        return elapsed < DEBOUNCE_SECONDS
    except (ValueError, TypeError):
        return False


def _mark_saved(session_id, session_key=None):
    """Record that we just saved for this session."""
    state = _load_state()
    state.setdefault("last_save", {})[session_id] = time.time()

    # Track session_key -> session_id mapping for session:end handler
    if session_key:
        state.setdefault("key_to_id", {})[session_key] = session_id

    # Prune old entries (keep last 50)
    saves = state["last_save"]
    if len(saves) > 50:
        sorted_keys = sorted(saves, key=lambda k: saves[k])
        for k in sorted_keys[:-50]:
            del saves[k]

    _save_state(state)


def _get_session_id_for_lookup(platform, user_id):
    """Look up the last known session_id for a platform:user_id combo."""
    state = _load_state()
    lookup_key = f"{platform}:{user_id}"
    return state.get("active_sessions", {}).get(lookup_key)


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

def _on_agent_start(context):
    """Search Supermemory for entities in the incoming message.

    Writes results to briefing file and injects pointer into MEMORY.md.
    """
    message = context.get("message", "")
    session_id = context.get("session_id", "")
    platform = context.get("platform", "")
    user_id = context.get("user_id", "")

    # Track a lookup key -> session_id for session:end (which lacks session_id)
    if session_id and platform and user_id:
        lookup_key = f"{platform}:{user_id}"
        state = _load_state()
        state.setdefault("active_sessions", {})[lookup_key] = session_id
        _save_state(state)

    if not message:
        return

    entities = _extract_entities(message)
    if not entities:
        # No entities found, but still do a general search with the message
        # if it's a new session or seems like a topic opener
        if len(message.split()) > 3:
            # Use first meaningful words as search query
            words = [w for w in message.split()[:10] if len(w) > 3]
            if words:
                entities = [" ".join(words[:5])]

    if not entities:
        return

    # Search for each entity
    results_by_entity = {}
    for entity in entities:
        results = _sm_search(entity, limit=3)
        if results:
            results_by_entity[entity] = results

    if not results_by_entity:
        return

    # Build briefing text
    briefing_lines = ["[Supermemory context for this message]"]
    for entity, results in results_by_entity.items():
        briefing_lines.append(f"\n--- {entity} ---")
        for r in results:
            chunks = r.get("chunks", [])
            if chunks:
                content = chunks[0].get("content", "").strip()
                if content:
                    # Truncate long chunks
                    if len(content) > 400:
                        content = content[:400] + "..."
                    briefing_lines.append(content)
    briefing_text = "\n".join(briefing_lines)

    # Inject directly into the agent's context prompt via the gateway hook API.
    # The gateway checks hook_ctx["inject_context"] after agent:start fires
    # and prepends it to the context_prompt for this agent run.
    context["inject_context"] = briefing_text

    # Also write briefing to file for debugging / manual inspection
    _write_briefing(results_by_entity)

    total = sum(len(r) for r in results_by_entity.values())
    print(
        f"[superbud-memory] agent:start: searched {len(entities)} entities, "
        f"found {total} results, injected into context",
        flush=True,
    )


def _on_agent_end(context):
    """Extract facts/decisions from the latest exchange and save to Supermemory."""
    session_id = context.get("session_id", "")
    message = context.get("message", "")
    response = context.get("response", "")

    if not session_id or not message:
        return

    # Debounce check
    if _should_debounce(session_id, message):
        return

    # Get the last few exchanges for context
    recent = _read_recent_transcript(session_id, last_n=4)
    if not recent:
        # Fall back to just the current exchange from hook context
        recent = [
            {"role": "user", "content": message},
        ]
        if response:
            recent.append({"role": "assistant", "content": response})

    # Build the transcript for the LLM
    transcript = "\n".join(
        f"{'USER' if m['role'] == 'user' else 'ASSISTANT'}: {m['content'][:500]}"
        for m in recent
    )

    # Call the extraction LLM
    system_prompt = (
        "You are a memory extraction engine. Given a conversation excerpt, "
        "extract ONLY facts worth remembering long-term. Output one fact per line. "
        "Each line should be a complete, self-contained statement. "
        "Focus on: decisions made, preferences stated, facts learned about people/companies/projects, "
        "action items committed to, corrections or clarifications. "
        "Skip: greetings, filler, task mechanics, tool outputs, things already obvious from context. "
        "If nothing is worth saving, output exactly: NONE"
    )

    extraction = _call_llm(system_prompt, transcript)
    if not extraction or extraction.strip().upper() == "NONE":
        _mark_saved(session_id)
        return

    # Parse and save each fact
    facts = [line.strip().lstrip("- ") for line in extraction.strip().split("\n") if line.strip() and line.strip() != "NONE"]

    saved = 0
    new_entities = []
    for fact in facts[:5]:  # Cap at 5 facts per exchange
        if len(fact) > 20:  # Skip trivially short "facts"
            _sm_save(fact, tags="hook:agent-end,auto-extracted")
            saved += 1
            # Extract entity names from the fact to grow the registry
            new_entities.extend(_regex_extract_entities(fact))

    if new_entities:
        _add_entities_to_registry(new_entities)

    if saved:
        _mark_saved(session_id)
        print(f"[superbud-memory] agent:end: saved {saved} facts for {session_id[:20]}", flush=True)


def _on_session_end(context):
    """Generate a full session summary and save to Supermemory."""
    platform = context.get("platform", "unknown")
    user_id = context.get("user_id", "")

    # session:end doesn't include session_id -- look it up from our tracking
    session_id = _get_session_id_for_lookup(platform, user_id)
    if not session_id:
        print("[superbud-memory] session:end: could not resolve session_id, skipping", flush=True)
        return

    # Read the full transcript
    transcript = _read_full_transcript(session_id)
    if not transcript or len(transcript) < 3:
        print("[superbud-memory] session:end: transcript too short, skipping", flush=True)
        return

    # Build condensed transcript (keep it under ~4K tokens)
    condensed = []
    total_chars = 0
    for m in transcript:
        content = m["content"][:400]
        condensed.append(f"{'USER' if m['role'] == 'user' else 'ASSISTANT'}: {content}")
        total_chars += len(content)
        if total_chars > 6000:
            condensed.append("... (transcript truncated)")
            break

    transcript_text = "\n".join(condensed)

    system_prompt = (
        "You are a session summarizer. Given a conversation transcript, write a concise "
        "session summary (3-8 sentences). Include: main topics discussed, key decisions made, "
        "action items, and any important facts or preferences revealed. "
        "Write in third person (e.g., 'Jordan discussed...'). "
        "Be specific with names, numbers, and details. Skip pleasantries and filler."
    )

    summary = _call_llm(system_prompt, transcript_text, max_tokens=600)
    if summary and summary.strip():
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        full_summary = f"Session summary ({ts}, {platform}): {summary.strip()}"
        _sm_save(full_summary, tags="hook:session-end,session-summary")
        print(f"[superbud-memory] session:end: summary saved ({len(summary)} chars)", flush=True)

    # Clean up the briefing file (stale after session end)
    try:
        if BRIEFING_FILE.exists():
            BRIEFING_FILE.unlink()
    except OSError:
        pass

    # Remove memory pointer
    _remove_memory_pointer()


# ---------------------------------------------------------------------------
# Main handler (called by hook registry)
# ---------------------------------------------------------------------------

def handle(event_type, context):
    """Dispatch events to the appropriate handler.

    All handlers are synchronous (no async). The hook registry supports both.
    Errors are caught by the registry so we don't need try/except here,
    but we add them for safety since we're doing I/O.
    """
    try:
        if event_type == "agent:start":
            _on_agent_start(context)
        elif event_type == "agent:end":
            _on_agent_end(context)
        elif event_type == "session:end":
            _on_session_end(context)
    except Exception as e:
        print(f"[superbud-memory] Error in {event_type}: {e}", flush=True)
