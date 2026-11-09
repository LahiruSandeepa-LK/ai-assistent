"""Conversation-memory workflow: session isolation, memory-as-RAG, per-user history."""
import os

from memory.conversation import ConversationStore


def test_new_session_is_isolated_and_fresh():
    s = ConversationStore()
    s.add_user("sessA", "what is the home loan rate?", user_id="u1")
    s.add_assistant("sessA", "11.5% p.a.", user_id="u1")
    # a brand-new session has no turns and nothing to retrieve
    assert s.relevant_turns("sessB", "home loan rate") == []
    assert s.recent_turns("sessB") == []


def test_relevant_turns_returns_only_relevant_within_session():
    s = ConversationStore()
    s.add_user("sX", "tell me about home loan interest rates", user_id="u1")
    s.add_assistant("sX", "Home loans are 11.5% p.a.", user_id="u1")
    s.add_user("sX", "what time does the branch open?", user_id="u1")
    s.add_assistant("sX", "9am to 3pm.", user_id="u1")
    hits = s.relevant_turns("sX", "home loan rate", k=2, threshold=0.0)
    assert hits and any("home loan" in t.lower() for _, t in hits)
    assert len(hits) <= 2


def test_list_user_sessions_per_user_excludes_current_and_limits():
    s = ConversationStore()
    for i in range(4):
        sid = f"s{i}"
        s.add_user(sid, f"question {i}", user_id="u1")
        s.add_assistant(sid, f"answer {i}", user_id="u1")
    # another user's session must not appear
    s.add_user("other", "not mine", user_id="u2")
    out = s.list_user_sessions("u1", limit=3, exclude_session="s3")
    assert len(out) == 3                          # limited to 3
    ids = {r["session_id"] for r in out}
    assert "s3" not in ids                        # current session excluded
    assert all(not any(t for t in r["turns"] if t[1] == "not mine") for r in out)  # no cross-user
    assert out[0]["title"]                        # has a title + transcript
    assert out[0]["turns"]


def test_history_is_not_fed_into_a_new_session():
    s = ConversationStore()
    s.add_user("old", "my secret topic was X", user_id="u1")
    s.add_assistant("old", "noted", user_id="u1")
    # a new session for the same user retrieves nothing from the old one (isolation)
    assert s.relevant_turns("new", "secret topic", k=3, threshold=0.0) == []
