/**
 * WhatsApp adapter — uses whatsapp-web.js for WebSocket/Web API events.
 * Handles QR authentication, message reception, image/file handling.
 */

import { ChannelType, InboundMessage, Attachment } from "../types";
import { BaseAdapter } from "./base";

interface WhatsAppMessage {
  from: string;
  body: string;
  hasMedia: boolean;
  media?: { mimetype: string; filename?: string; data?: Buffer };
  timestamp?: string;
  _data?: { notifyName?: string };
}

interface WhatsAppClient {
  on(event: "qr", cb: (qr: string) => void): void;
  on(event: "ready", cb: () => void): void;
  on(event: "message", cb: (msg: WhatsAppMessage) => void): void;
  initialize(): Promise<void>;
  sendMessage(to: string, text: string): Promise<unknown>;
  sendMedia(to: string, media: { media: Buffer; caption?: string }): Promise<unknown>;
}

export class WhatsAppAdapter extends BaseAdapter {
  readonly channel = ChannelType.WHATSAPP;
  private client: WhatsAppClient | null = null;
  private qrCode = "";

  async listen(handler: (msg: InboundMessage) => Promise<void>): Promise<void> {
    const { Client, LocalAuth } = await import("whatsapp-web.js");

    this.client = new Client({
      authStrategy: new LocalAuth(),
      puppeteer: { headless: true, args: ["--no-sandbox"] },
    }) as unknown as WhatsAppClient;

    this.client.on("qr", (qr: string) => {
      this.qrCode = qr;
      console.log("[WhatsApp] QR received — scan with WhatsApp to authenticate");
    });

    this.client.on("ready", () => {
      console.log("[WhatsApp] Client ready — receiving messages");
    });

    this.client.on("message", async (msg: WhatsAppMessage) => {
      const inbound = this.normalizeRaw(msg);
      if (inbound) await handler(inbound);
    });

    await this.client.initialize();
  }

  getQR(): string {
    return this.qrCode;
  }

  async send(target: string, text: string, _threadId?: string): Promise<boolean> {
    if (!this.client) return false;
    try {
      await this.client.sendMessage(target, text);
      return true;
    } catch (e) {
      console.error("[WhatsApp] Send error:", e);
      return false;
    }
  }

  async sendFile(target: string, filePath: string, caption?: string): Promise<boolean> {
    if (!this.client) return false;
    try {
      const fs = await import("fs/promises");
      const media = await fs.readFile(filePath);
      await this.client.sendMedia(target, { media, caption });
      return true;
    } catch (e) {
      console.error("[WhatsApp] SendFile error:", e);
      return false;
    }
  }

  normalize(raw: Record<string, unknown>): InboundMessage | null {
    return this.normalizeRaw(raw as unknown as WhatsAppMessage);
  }

  private normalizeRaw(msg: WhatsAppMessage): InboundMessage | null {
    if (!msg.body && !msg.hasMedia) return null;

    const attachments: Attachment[] = [];
    if (msg.hasMedia && msg.media) {
      attachments.push({
        type: msg.media.mimetype?.startsWith("image/") ? "image" : "file",
        name: msg.media.filename || "media",
        mimeType: msg.media.mimetype,
        data: msg.media.data,
      });
    }

    return {
      content: msg.body || "",
      channel: this.channel,
      senderId: msg.from,
      senderName: msg._data?.notifyName || msg.from,
      channelId: msg.from,
      threadId: msg.from,
      attachments,
      raw: msg as unknown as Record<string, unknown>,
      timestamp: msg.timestamp || new Date().toISOString(),
    };
  }
}
