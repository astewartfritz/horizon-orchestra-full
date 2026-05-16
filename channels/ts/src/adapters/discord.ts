import { ChannelType, InboundMessage, Attachment } from "../types";
import { BaseAdapter } from "./base";

export class DiscordAdapter extends BaseAdapter {
  readonly channel = ChannelType.DISCORD;

  normalize(raw: Record<string, unknown>): InboundMessage | null {
    if (!raw.content && !raw.attachments) return null;
    const atts = (raw.attachments || []) as Array<Record<string, unknown>>;
    const attachments: Attachment[] = atts
      .filter((a) => (a.content_type as string || "").startsWith("image/"))
      .map((a) => ({ type: "image", url: a.url as string, name: (a.filename as string) || "image" }));

    return {
      content: (raw.content as string) || "",
      channel: this.channel,
      senderId: (raw.author as Record<string, unknown>)?.id as string || "unknown",
      senderName: (raw.author as Record<string, unknown>)?.username as string || "unknown",
      channelId: (raw.channel_id as string) || "",
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
        body: JSON.stringify({ content: text }),
      });
      return res.status === 204;
    } catch {
      return false;
    }
  }
}
