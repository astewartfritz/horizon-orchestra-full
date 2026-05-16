import { ChannelType, ChannelAdapter, InboundMessage } from "../types";

export abstract class BaseAdapter implements ChannelAdapter {
  abstract readonly channel: ChannelType;
  protected log: (...args: unknown[]) => void = console.log;

  abstract normalize(raw: Record<string, unknown>): InboundMessage | null;

  abstract send(target: string, text: string, threadId?: string): Promise<boolean>;

  async sendFile(target: string, filePath: string, caption?: string): Promise<boolean> {
    this.log(`[${this.channel}] sendFile not implemented: ${filePath}`);
    return false;
  }

  /** Build a standardized error response about image support */
  imageNotSupported(attachmentName: string, modelName: string): string {
    return (
      `Cannot read "${attachmentName}" (${modelName} does not support image input). ` +
      `Inform the user and try again without an image, ` +
      `or switch to a vision-capable model like llava or gpt-4o.`
    );
  }

  /** Route a normalized message to the Orchestra Python backend */
  async routeToOrchestra(
    apiUrl: string,
    msg: InboundMessage,
    apiKey?: string
  ): Promise<string> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "x-trace-id": Math.random().toString(36).slice(2, 14),
    };
    if (apiKey) headers["Authorization"] = `Bearer ${apiKey}`;

    try {
      const fetch = (await import("node-fetch")).default || (await import("node-fetch"));
      const res = await fetch(`${apiUrl}/api/chat`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          task: msg.content,
          provider: "ollama",
          model: "nemotron-mini",
          session_id: msg.threadId || msg.senderId,
        }),
      });
      const data = await res.json() as { task_id?: string };
      return data.task_id || "unknown";
    } catch (e) {
      this.log(`[${this.channel}] Route error:`, e);
      return `Error: ${e}`;
    }
  }

  /** Wait for the agent response via SSE stream */
  protected async waitForResponse(apiUrl: string, taskId: string): Promise<string> {
    try {
      const fetch = (await import("node-fetch")).default || (await import("node-fetch"));
      const EventSource = (await import("eventsource")).default;
      return new Promise((resolve) => {
        const es = new EventSource(`${apiUrl}/api/chat/${taskId}/stream`);
        let lastResult = "";
        es.onmessage = (event: MessageEvent) => {
          try {
            const msg = JSON.parse(event.data);
            if (msg.type === "result") lastResult = msg.data?.content || "";
            if (msg.type === "done") {
              es.close();
              resolve(lastResult || msg.data?.result || "");
            }
            if (msg.type === "token") lastResult += msg.data || "";
          } catch {}
        };
        es.onerror = () => {
          es.close();
          resolve(lastResult || "Stream error");
        };
        setTimeout(() => {
          es.close();
          resolve(lastResult || "Timeout");
        }, 300000);
      });
    } catch {
      return "Response stream unavailable";
    }
  }
}
