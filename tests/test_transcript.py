from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from orchid.claude.transcript import normalize_stream_message


def _result(**over):
    base = dict(
        subtype="success",
        duration_ms=4200,
        duration_api_ms=4000,
        is_error=False,
        num_turns=1,
        session_id="sid-1",
        total_cost_usd=0.0123,
    )
    base.update(over)
    return ResultMessage(**base)


def test_system_messages_skipped():
    assert normalize_stream_message(SystemMessage(subtype="init", data={"session_id": "x"})) is None


def test_assistant_blocks():
    msg = AssistantMessage(
        content=[
            TextBlock(text="hello"),
            ThinkingBlock(thinking="hmm", signature="s"),
            ToolUseBlock(id="tu1", name="Read", input={"file_path": "/x"}),
        ],
        model="m",
        uuid="u-1",
    )
    nm = normalize_stream_message(msg)
    assert nm is not None and nm.role == "assistant" and nm.uuid == "u-1"
    types = [b.type for b in nm.blocks]
    assert types == ["text", "thinking", "tool_use"]
    assert nm.blocks[2].name == "Read"
    assert "file_path" in nm.blocks[2].input_preview


def test_user_prompt_included_and_tool_results_kept():
    nm = normalize_stream_message(UserMessage(content="hi"))
    assert nm is not None and nm.role == "user"
    assert nm.blocks[0].type == "text"
    assert nm.blocks[0].text == "hi"
    assert normalize_stream_message(UserMessage(content="")) is None
    nm2 = normalize_stream_message(
        UserMessage(content=[ToolResultBlock(tool_use_id="tu1", content="out", is_error=False)])
    )
    assert nm2 is not None and nm2.role == "user"
    assert nm2.blocks[0].type == "tool_result"
    assert nm2.blocks[0].content_preview == "out"


def test_tool_result_list_content_flattened():
    nm = normalize_stream_message(
        UserMessage(content=[ToolResultBlock(tool_use_id="t", content=[{"type": "text", "text": "abc"}])])
    )
    assert nm.blocks[0].content_preview == "abc"


def test_truncation():
    big = "x" * 20000
    nm = normalize_stream_message(
        AssistantMessage(content=[ToolUseBlock(id="t", name="Bash", input={"cmd": big})], model="m")
    )
    assert nm.blocks[0].truncated is True
    assert len(nm.blocks[0].input_preview) == 16384


def test_result_divider():
    nm = normalize_stream_message(_result())
    assert nm.role == "result"
    assert nm.blocks[0].text == "turn done · $0.0123 · 4.2s"
    nm2 = normalize_stream_message(_result(total_cost_usd=None))
    assert nm2.blocks[0].text == "turn done · 4.2s"
