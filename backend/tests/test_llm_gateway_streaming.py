from types import SimpleNamespace

from app.core.llm.gateway import LLMGateway


async def test_chat_stream_normalizes_split_tool_call_chunks(monkeypatch):
    class Response:
        def __aiter__(self):
            async def values():
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content=None,
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        id="call-file-write",
                                        function=SimpleNamespace(
                                            name="file_write",
                                            arguments="",
                                        ),
                                    )
                                ],
                            )
                        )
                    ]
                )
                yield SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(
                                content=None,
                                tool_calls=[
                                    SimpleNamespace(
                                        index=0,
                                        id=None,
                                        function=SimpleNamespace(
                                            name=None,
                                            arguments='{"path":"w6/x.py"}',
                                        ),
                                    )
                                ],
                            )
                        )
                    ]
                )

            return values()

    async def fake_get_config(self, tenant_id, name):
        return {
            "name": name,
            "model": "openai/mock-model",
            "api_base": "http://mock/v1",
            "api_key": "sk-test",
            "embedding_model": "embedding-3",
        }

    async def fake_completion(**kwargs):
        return Response()

    monkeypatch.setattr(LLMGateway, "get_config", fake_get_config)
    monkeypatch.setattr("app.core.llm.gateway.litellm.acompletion", fake_completion)

    events = [
        event
        async for event in LLMGateway().chat_stream(
            "default",
            [{"role": "user", "content": "write a file"}],
            tools=[{"type": "function", "function": {"name": "file_write"}}],
            tenant_id="tenant-id",
        )
    ]

    assert events == [
        {
            "type": "tool_call",
            "index": 0,
            "id": "call-file-write",
            "name": "file_write",
            "arguments": "",
        },
        {
            "type": "tool_call",
            "index": 0,
            "id": "",
            "name": "",
            "arguments": '{"path":"w6/x.py"}',
        },
    ]
