import re
from typing import Callable


class OutputFormatter:
    def __init__(self):
        self._formatters: dict[str, Callable] = {
            "slack": self._format_slack,
            "discord": self._format_discord,
            "telegram": self._format_telegram,
            "whatsapp": self._format_whatsapp,
            "email": self._format_email,
            "imessage": self._format_imessage,
            "web": self._format_web,
            "default": self._format_default,
        }

    def register_formatter(self, channel_type: str, formatter: Callable):
        self._formatters[channel_type] = formatter

    def format(self, text: str, channel_type: str, **kwargs) -> str:
        formatter = self._formatters.get(channel_type, self._formatters["default"])
        return formatter(text, **kwargs)

    def _format_slack(self, text: str, **kwargs) -> str:
        text = re.sub(r'\*\*\*(.+?)\*\*\*', r'***\1***', text)
        text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)
        text = re.sub(r'```(\w+)?\n(.*?)```', r'```\1\n\2```', text, flags=re.DOTALL)
        text = re.sub(r'`(.+?)`', r'`\1`', text)
        return text

    def _format_discord(self, text: str, **kwargs) -> str:
        text = re.sub(r'\*\*\*(.+?)\*\*\*', r'***\1***', text)
        text = re.sub(r'\*\*(.+?)\*\*', r'**\1**', text)
        return text

    def _format_telegram(self, text: str, **kwargs) -> str:
        text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', text)
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'```(\w+)?\n(.*?)```', r'<pre>\2</pre>', text, flags=re.DOTALL)
        text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
        return text

    def _format_whatsapp(self, text: str, **kwargs) -> str:
        return re.sub(r'```[\s\S]*?```', '', text)

    def _format_email(self, text: str, **kwargs) -> str:
        lines = []
        in_code = False
        for line in text.split("\n"):
            if line.startswith("```"):
                in_code = not in_code
                if in_code:
                    lines.append('<pre style="background:#f4f4f4;padding:10px;border-radius:4px;font-family:monospace;">')
                else:
                    lines.append("</pre>")
                continue
            if in_code:
                lines.append(line)
            elif line.startswith("## "):
                lines.append(f"<h2>{line[3:]}</h2>")
            elif line.startswith("### "):
                lines.append(f"<h3>{line[4:]}</h3>")
            elif line.startswith("- "):
                lines.append(f"<li>{line[2:]}</li>")
            elif re.match(r'^\d+\. ', line):
                lines.append(f"<li>{line.split('. ', 1)[1]}</li>")
            elif line.strip():
                lines.append(f"<p>{line}</p>")
            else:
                lines.append("<br>")
        return "".join(lines)

    def _format_imessage(self, text: str, **kwargs) -> str:
        return re.sub(r'```[\s\S]*?```', '[code block]', text)

    def _format_web(self, text: str, **kwargs) -> str:
        return text

    def _format_default(self, text: str, **kwargs) -> str:
        return text
