# -*- coding: utf-8 -*-
"""
邮件收发 Tool — 支持 QQ邮箱 / Gmail / Outlook

配置项（config.py）：
    EMAIL_IMAP_SERVER   IMAP 服务器地址
    EMAIL_SMTP_SERVER   SMTP 服务器地址
    EMAIL_ADDRESS       邮箱地址
    EMAIL_PASSWORD      授权码（非登录密码）
    EMAIL_SMTP_PORT     SMTP 端口（默认 465 SSL）
"""

import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from typing import Any, Dict, List, Optional
import logging

from tools.base import Tool

logger = logging.getLogger(__name__)

# 常见邮箱的预设配置
EMAIL_PRESETS = {
    "qq": {
        "imap": "imap.qq.com",
        "smtp": "smtp.qq.com",
        "smtp_port": 465,
    },
    "gmail": {
        "imap": "imap.gmail.com",
        "smtp": "smtp.gmail.com",
        "smtp_port": 465,
    },
    "outlook": {
        "imap": "outlook.office365.com",
        "smtp": "smtp.office365.com",
        "smtp_port": 587,  # STARTTLS
    },
    "163": {
        "imap": "imap.163.com",
        "smtp": "smtp.163.com",
        "smtp_port": 465,
    },
}


def _decode_header_value(value: str) -> str:
    """解码邮件头（可能是 base64/quoted-printable 编码的中文）"""
    if not value:
        return ""
    decoded_parts = decode_header(value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return "".join(result)


def _safe_decode(payload: bytes, charset: str) -> str:
    """安全解码邮件内容，处理非标准编码"""
    if not payload:
        return ""
    # 常见的非标准编码映射
    charset_map = {
        "unknown-8bit": "utf-8",
        "x-unknown": "utf-8",
        "default": "utf-8",
        "": "utf-8",
    }
    charset = (charset or "utf-8").lower().strip()
    charset = charset_map.get(charset, charset)
    for enc in [charset, "utf-8", "gbk", "gb2312", "latin-1"]:
        try:
            return payload.decode(enc, errors="replace")
        except (UnicodeDecodeError, LookupError):
            continue
    return payload.decode("utf-8", errors="replace")


def _get_email_config():
    """从 config.py 读取邮箱配置"""
    try:
        import config
        addr = getattr(config, "EMAIL_ADDRESS", "")
        if not addr:
            return None

        # 自动检测邮箱类型
        preset_key = None
        for key in EMAIL_PRESETS:
            if f"@{key}." in addr.lower() or addr.lower().endswith(f"@{key}.com"):
                preset_key = key
                break

        preset = EMAIL_PRESETS.get(preset_key, {})

        return {
            "address": addr,
            "password": getattr(config, "EMAIL_PASSWORD", ""),
            "imap_server": getattr(config, "EMAIL_IMAP_SERVER", "") or preset.get("imap", ""),
            "smtp_server": getattr(config, "EMAIL_SMTP_SERVER", "") or preset.get("smtp", ""),
            "smtp_port": int(getattr(config, "EMAIL_SMTP_PORT", 0) or preset.get("smtp_port", 465)),
        }
    except Exception as e:
        logger.error(f"读取邮箱配置失败: {e}")
        return None


class ReadEmailTool(Tool):
    """读取最近的邮件"""

    @property
    def name(self) -> str:
        return "read_email"

    @property
    def description(self) -> str:
        return "读取邮箱中最近的邮件。可以指定读取数量和文件夹（默认收件箱）。返回发件人、主题、时间和正文摘要。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "读取邮件数量，默认5",
                    "default": 5,
                },
                "folder": {
                    "type": "string",
                    "description": "邮件文件夹，默认INBOX（收件箱）",
                    "default": "INBOX",
                },
                "unread_only": {
                    "type": "boolean",
                    "description": "是否只读未读邮件，默认false",
                    "default": False,
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs) -> Dict[str, Any]:
        cfg = _get_email_config()
        if not cfg or not cfg["address"]:
            return {"success": False, "error": "邮箱未配置，请在设置中配置邮箱地址和授权码"}

        count = kwargs.get("count", 5)
        folder = kwargs.get("folder", "INBOX")
        unread_only = kwargs.get("unread_only", False)

        try:
            # 连接 IMAP
            mail = imaplib.IMAP4_SSL(cfg["imap_server"])
            mail.login(cfg["address"], cfg["password"])
            mail.select(folder)

            # 搜索邮件
            search_criteria = "(UNSEEN)" if unread_only else "ALL"
            status, data = mail.search(None, search_criteria)
            if status != "OK":
                mail.logout()
                return {"success": False, "error": "搜索邮件失败"}

            mail_ids = data[0].split()
            if not mail_ids:
                mail.logout()
                return {"success": True, "result": "没有邮件" if not unread_only else "没有未读邮件"}

            # 取最近 N 封
            recent_ids = mail_ids[-count:]
            recent_ids.reverse()  # 最新的在前

            emails = []
            for mid in recent_ids:
                status, msg_data = mail.fetch(mid, "(RFC822)")
                if status != "OK":
                    continue

                msg = email.message_from_bytes(msg_data[0][1])

                # 解析头部
                subject = _decode_header_value(msg.get("Subject", ""))
                from_addr = _decode_header_value(msg.get("From", ""))
                date_str = msg.get("Date", "")

                # 解析正文
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        if content_type == "text/plain":
                            payload = part.get_payload(decode=True)
                            charset = part.get_content_charset() or "utf-8"
                            body = _safe_decode(payload, charset)
                            break
                        elif content_type == "text/html" and not body:
                            payload = part.get_payload(decode=True)
                            charset = part.get_content_charset() or "utf-8"
                            body = _safe_decode(payload, charset)
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        charset = msg.get_content_charset() or "utf-8"
                        body = _safe_decode(payload, charset)

                # 截断正文
                body = body.strip()
                if len(body) > 500:
                    body = body[:500] + "..."

                emails.append({
                    "from": from_addr,
                    "subject": subject,
                    "date": date_str,
                    "body": body,
                })

            mail.logout()

            # 格式化输出
            lines = []
            for i, e in enumerate(emails, 1):
                lines.append(f"📧 {i}. {e['subject']}")
                lines.append(f"   发件人: {e['from']}")
                lines.append(f"   时间: {e['date']}")
                lines.append(f"   内容: {e['body'][:200]}")
                lines.append("")

            return {"success": True, "result": "\n".join(lines)}

        except imaplib.IMAP4.error as e:
            return {"success": False, "error": f"IMAP 登录失败（检查授权码）: {str(e)}"}
        except Exception as e:
            logger.error(f"读取邮件失败: {e}")
            return {"success": False, "error": f"读取邮件失败: {str(e)}"}


class SendEmailTool(Tool):
    """发送邮件"""

    @property
    def name(self) -> str:
        return "send_email"

    @property
    def description(self) -> str:
        return "发送邮件。需要指定收件人、主题和正文内容。"

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "收件人邮箱地址",
                },
                "subject": {
                    "type": "string",
                    "description": "邮件主题",
                },
                "body": {
                    "type": "string",
                    "description": "邮件正文内容",
                },
            },
            "required": ["to", "subject", "body"],
        }

    async def execute(self, **kwargs) -> Dict[str, Any]:
        cfg = _get_email_config()
        if not cfg or not cfg["address"]:
            return {"success": False, "error": "邮箱未配置，请在设置中配置邮箱地址和授权码"}

        to_addr = kwargs.get("to", "")
        subject = kwargs.get("subject", "")
        body = kwargs.get("body", "")

        if not to_addr:
            return {"success": False, "error": "请指定收件人邮箱地址"}
        if not subject:
            return {"success": False, "error": "请指定邮件主题"}

        try:
            # 构建邮件
            msg = MIMEMultipart()
            msg["From"] = cfg["address"]
            msg["To"] = to_addr
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", "utf-8"))

            # 发送
            smtp_port = cfg["smtp_port"]
            if smtp_port == 587:
                # STARTTLS（Outlook）
                server = smtplib.SMTP(cfg["smtp_server"], smtp_port)
                server.starttls()
            else:
                # SSL（QQ/Gmail/163）
                server = smtplib.SMTP_SSL(cfg["smtp_server"], smtp_port)

            server.login(cfg["address"], cfg["password"])
            server.send_message(msg)
            server.quit()

            return {"success": True, "result": f"邮件已发送给 {to_addr}，主题: {subject}"}

        except smtplib.SMTPAuthenticationError:
            return {"success": False, "error": "SMTP 认证失败，请检查邮箱地址和授权码"}
        except Exception as e:
            logger.error(f"发送邮件失败: {e}")
            return {"success": False, "error": f"发送邮件失败: {str(e)}"}
