import { ChannelType, ChannelAdapter } from "../types";
import { SlackAdapter } from "./slack";
import { TelegramAdapter } from "./telegram";
import { DiscordAdapter } from "./discord";
import { WhatsAppAdapter } from "./whatsapp";
import { IMessagesAdapter } from "./imessage";
import { EmailAdapter } from "./email";

const REGISTRY: [ChannelType, () => ChannelAdapter][] = [
  [ChannelType.SLACK, () => new SlackAdapter()],
  [ChannelType.TELEGRAM, () => new TelegramAdapter()],
  [ChannelType.DISCORD, () => new DiscordAdapter()],
  [ChannelType.WHATSAPP, () => new WhatsAppAdapter()],
  [ChannelType.IMESSAGE, () => new IMessagesAdapter()],
  [ChannelType.EMAIL, () => new EmailAdapter()],
];

const REGISTRY_MAP = new Map<ChannelType, () => ChannelAdapter>(REGISTRY);

export function getAdapter(channel: ChannelType): ChannelAdapter {
  const factory = REGISTRY_MAP.get(channel);
  if (!factory) throw new Error(`No adapter for channel: ${channel}`);
  return factory();
}

export function listAdapters(): ChannelType[] {
  return Array.from(REGISTRY_MAP.keys());
}
