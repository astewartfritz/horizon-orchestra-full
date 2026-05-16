import { ChannelType, InboundMessage } from "../types";
import { BaseAdapter } from "./base";

export class EmailAdapter extends BaseAdapter {
  readonly channel = ChannelType.EMAIL;

  normalize(raw: Record<string, unknown>): InboundMessage | null {
    return {
      content: (raw.body as string) || (raw.text as string) || "",
      channel: this.channel,
      senderId: (raw.from as string) || "unknown",
      senderName: (raw.from as string) || "unknown",
      channelId: (raw.to as string) || "",
      threadId: (raw.messageId as string) || (raw["message-id"] as string),
      attachments: [],
      raw,
      timestamp: new Date().toISOString(),
    };
  }

  async send(target: string, text: string, _threadId?: string): Promise<boolean> {
    try {
      const nodemailer = await import("nodemailer");
      const host = process.env.EMAIL_HOST || "localhost";
      const port = process.env.EMAIL_PORT || "25";
      const transporter = nodemailer.createTransport({
        host,
        port: parseInt(port),
        secure: port === "465",
        auth: process.env.EMAIL_USER ? { user: process.env.EMAIL_USER, pass: process.env.EMAIL_PASS || "" } : undefined,
      });
      await transporter.sendMail({
        from: process.env.EMAIL_FROM || "orchestra@localhost",
        to: target,
        subject: "Orchestra Response",
        text,
      });
      return true;
    } catch (e) {
      console.error("[Email] Send error:", e);
      return false;
    }
  }

  /** Poll an IMAP inbox for new emails */
  async listen(handler: (msg: InboundMessage) => Promise<void>): Promise<void> {
    try {
      const Imap = (await import("imap")).default;
      const imap = new Imap({
        user: process.env.EMAIL_USER || "",
        password: process.env.EMAIL_PASS || "",
        host: process.env.EMAIL_HOST || "imap.gmail.com",
        port: 993,
        tls: true,
      });
      imap.on("mail", () => {
        console.log("[Email] New mail received");
      });
      imap.connect();
    } catch (e) {
      console.warn("[Email] IMAP polling not available:", e);
    }
  }
}
