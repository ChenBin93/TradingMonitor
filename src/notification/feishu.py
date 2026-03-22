from datetime import datetime
from typing import Any, Optional
from loguru import logger


class FeishuClient:
    def __init__(
        self,
        app_id: str = "",
        app_secret: str = "",
        chat_id: str = "",
        webhook_url: str = "",
        long_connection: bool = True,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.chat_id = chat_id
        self.webhook_url = webhook_url
        self.long_connection = long_connection
        self._ws_running = False
        self._pending_commands: list[tuple[str, datetime]] = []

    def send_message(self, message: str):
        if not message:
            return
        if self.webhook_url:
            self._send_webhook(message)
        elif self.long_connection and self.app_id and self.app_secret:
            self._send_api(message)

    def _send_webhook(self, message: str):
        import requests
        try:
            payload = {"msg_type": "text", "content": {"text": message}}
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            if resp.status_code == 200:
                logger.info("Feishu webhook message sent")
            else:
                logger.warning(f"Feishu webhook error: {resp.status_code}")
        except Exception as e:
            logger.error(f"Feishu webhook failed: {e}")

    def _send_api(self, message: str):
        try:
            import lark_oapi as lark
            client = lark.Client.builder().app_id(self.app_id).app_secret(self.app_secret).build()
            request = (
                lark.api.im.v1.CreateMessageRequest.builder()
                .receive_id_type("chat_id")
                .request_body(
                    lark.api.im.v1.CreateMessageRequestBody.builder()
                    .receive_id(self.chat_id)
                    .msg_type("text")
                    .content(lark.JSON.marshal({"text": message}))
                    .build()
                )
                .build()
            )
            resp = client.im.v1.message.create(request)
            if resp.code == 0:
                logger.info("Feishu API message sent")
            else:
                logger.warning(f"Feishu API error: {resp.msg}")
        except Exception as e:
            logger.error(f"Feishu API send failed: {e}")

    def get_pending_commands(self) -> list[tuple[str, datetime]]:
        cmds = self._pending_commands[:]
        self._pending_commands.clear()
        return cmds


class CommandHandler:
    def __init__(self, on_scan: Optional[Any] = None, on_status: Optional[Any] = None):
        self.on_scan = on_scan
        self.on_status = on_status
        self._handlers = {
            "状态": self._handle_status,
            "扫描": self._handle_scan,
            "帮助": self._handle_help,
            "预警": self._handle_alerts,
            "排名": self._handle_ranking,
        }

    def handle(self, text: str) -> Optional[str]:
        text = text.strip().lower()
        for cmd, handler in self._handlers.items():
            if cmd in text:
                return handler(text)
        return None

    def _handle_status(self, text: str) -> str | None:
        return "系统运行正常"

    def _handle_scan(self, text: str) -> str | None:
        if self.on_scan:
            self.on_scan()
        return "收到扫描指令，下次扫描时执行"

    def _handle_help(self, text: str) -> str | None:
        return "可用命令: 状态, 扫描, 帮助, 预警, 排名"

    def _handle_alerts(self, text: str) -> str | None:
        return "最近预警: 暂无"

    def _handle_ranking(self, text: str) -> str | None:
        return "强弱排名: 暂无数据"
