import { ChannelType, InboundMessage } from "../types";
import { BaseAdapter } from "./base";

/**
 * iMessage adapter — uses macOS AppleScript to send/receive messages.
 * Only works on macOS. Falls back gracefully on other platforms.
 */
export class IMessagesAdapter extends BaseAdapter {
  readonly channel = ChannelType.IMESSAGE;

  normalize(raw: Record<string, unknown>): InboundMessage | null {
    return {
      content: (raw.text as string) || "",
      channel: this.channel,
      senderId: (raw.sender as string) || "unknown",
      senderName: (raw.sender as string) || "unknown",
      channelId: "",
      attachments: [],
      raw,
      timestamp: new Date().toISOString(),
    };
  }

  async send(target: string, text: string): Promise<boolean> {
    try {
      const { execSync } = await import("child_process");
      const escaped = text.replace(/"/g, '\\"');
      execSync(
        `osascript -e 'tell application "Messages" to send "${escaped}" to buddy "${target}"'`,
        { timeout: 10000 }
      );
      return true;
    } catch {
      console.warn("[iMessage] Requires macOS");
      return false;
    }
  }
}
