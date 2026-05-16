/**
 * Core message types for Orchestra's multi-channel ingestion system.
 * All platform adapters normalize into these interfaces.
 */

export enum ChannelType {
  CLI = "cli",
  SLACK = "slack",
  TELEGRAM = "telegram",
  DISCORD = "discord",
  WEB = "web",
  WHATSAPP = "whatsapp",
  REPL = "repl",
  IMESSAGE = "imessage",
  EMAIL = "email",
}

export interface Attachment {
  type: "image" | "file" | "audio" | "video";
  url?: string;
  name: string;
  mimeType?: string;
  data?: Buffer;
  fileId?: string;
}

export interface InboundMessage {
  content: string;
  channel: ChannelType;
  senderId: string;
  senderName: string;
  channelId: string;
  threadId?: string;
  attachments: Attachment[];
  raw: Record<string, unknown>;
  timestamp: string;
}

export interface OutboundMessage {
  text: string;
  channel: ChannelType;
  target: string;
  threadId?: string;
}

export interface AdapterConfig {
  enabled: boolean;
  credentials: Record<string, string>;
  webhookUrl?: string;
}

export interface ChannelAdapter {
  readonly channel: ChannelType;

  /** Normalize a platform-specific payload into InboundMessage */
  normalize(raw: Record<string, unknown>): InboundMessage | null;

  /** Send a text message to a platform target */
  send(target: string, text: string, threadId?: string): Promise<boolean>;

  /** Send a file (image, document) to a platform target */
  sendFile?(target: string, filePath: string, caption?: string): Promise<boolean>;

  /** Start listening for real-time events (WebSocket, polling) */
  listen?(handler: (msg: InboundMessage) => Promise<void>): Promise<void>;
}

export interface RouterConfig {
  orchestraApiUrl: string;
  apiKey?: string;
}
