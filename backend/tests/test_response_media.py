"""最终生成约束不会覆盖真实用户问题。"""

import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage, SystemMessage


class FinalPromptTests(unittest.IsolatedAsyncioTestCase):
    async def test_generation_constraint_does_not_replace_the_user_question(self):
        from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
        from langchain_core.messages import AIMessage

        from backend.app.agent import graph

        model = FakeMessagesListChatModel(
            responses=[AIMessage(content="你好，请直接描述你的问题。")]
        )
        # 回调读取实际送入模型的消息，而不是仅检查提示词文件中的字符串。
        from langchain_core.callbacks import BaseCallbackHandler

        captured = []

        class Capture(BaseCallbackHandler):
            def on_chat_model_start(self, serialized, messages, **kwargs):
                captured.extend(messages[0])

        model.callbacks = [Capture()]
        question = "请介绍商品的功能和使用限制"
        with patch.object(graph, "get_chat_model", return_value=model):
            await graph.finalize(
                {"react_messages": [SystemMessage("原系统提示"), HumanMessage(question)]}
            )
        self.assertEqual([m.content for m in captured if isinstance(m, HumanMessage)], [question])
        self.assertIsInstance(captured[-1], SystemMessage)
