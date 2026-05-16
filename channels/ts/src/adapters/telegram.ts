import { ChannelType, InboundMessage, Attachment } from "../types";
import { BaseAdapter } from "./base";

export class TelegramAdapter extends BaseAdapter {
  readonly channel = ChannelType.TELEGRAM;

  normalize(raw: Record<string, unknown>): InboundMessage | null {
    const msg = (raw.message || raw) as Record<string, unknown>;
    if (!msg.text && !msg.caption && !msg.photo) return null;

    const attachments: Attachment[] = [];
    if (msg.photo) {
      const photos = msg.photo as Array<Record<string, unknown>>;
      const largest = photos[photos.length - 1];
      attachments.push({ type: "image", fileId: largest.file_id as string, name: "photo.jpg" });
    }

    return {
      content: (msg.text as string) || (msg.caption as string) || "",
      channel: this.channel,
      senderId: String((msg.from as Record<string, unknown>)?.id || "unknown"),
      senderName: (msg.from as Record<string, unknown>)?.first_name as string || "unknown",
      channelId: String((msg.chat as Record<string, unknown>)?.id || ""),
      attachments,
      raw,
      timestamp: new Date().toISOString(),
    };
  }

  async send(botToken: string, chatId: string, text: string): Promise<boolean> {
    try {
      const { default: fetch } = await import("node-fetch");
      const url = `https://api.telegram.org/bot${botToken}/sendMessage`;
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: chatId, text }),
      });
      return res.status === 200;
    } catch {
      return false;
    }
  }
}
