import { ChannelType, InboundMessage, Attachment } from "../types";
import { BaseAdapter } from "./base";

export class SlackAdapter extends BaseAdapter {
  readonly channel = ChannelType.SLACK;

  normalize(raw: Record<string, unknown>): InboundMessage | null {
    const event = (raw.event || raw) as Record<string, unknown>;
    if (event.type !== "message" || event.subtype) return null;

    const files = (event.files || []) as Array<Record<string, unknown>>;
    const attachments: Attachment[] = files
      .filter((f) => (f.mimetype as string || "").startsWith("image/"))
      .map((f) => ({ type: "image", url: f.url_private as string, name: (f.name as string) || "image" }));

    return {
      content: (event.text as string) || "",
      channel: this.channel,
      senderId: (event.user as string) || "unknown",
      senderName: (event.user as string) || "unknown",
      channelId: (event.channel as string) || "",
      threadId: (event.thread_ts as string) || (event.ts as string) || "",
      attachments,
      raw,
      timestamp: new Date().toISOString(),
    };
  }

  async send(webhookUrl: string, text: string): Promise<boolean> {
    try {
      const { default: fetch } = await import("node-fetch");
      const res = await fetch(webhookUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      return res.status === 200;
    } catch {
      return false;
    }
  }
}
