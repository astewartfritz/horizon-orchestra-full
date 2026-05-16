/**
 * Orchestra Channels Server — TypeScript-based multi-channel message ingestion.
 *
 * Handles Slack, Telegram, WhatsApp, Discord, iMessage, and Email adapters.
 * Routes normalized messages to the Orchestra Python backend via REST API.
 */

import express from "express";
import { ChannelType, InboundMessage } from "../types";
import { getAdapter, listAdapters } from "../adapters/registry";

const app = express();
const PORT = parseInt(process.env.CHANNELS_PORT || "4500");
const ORCHESTRA_API_URL = process.env.ORCHESTRA_API_URL || "http://127.0.0.1:8000";

app.use(express.json({ limit: "50mb" }));
app.use(express.urlencoded({ extended: true }));

// ── Health ────────────────────────────────────────────────

app.get("/health", (_req, res) => {
  res.json({
    status: "ok",
    service: "orchestra-channels",
    version: "1.0.0",
    adapters: listAdapters().map((c) => c.toString()),
  });
});

// ── Generic webhook receiver ─────────────────────────────

app.post("/webhook/:channel", async (req, res) => {
  const { channel } = req.params;
  let ct: ChannelType;

  try {
    ct = channel.toUpperCase() as unknown as ChannelType;
    // Handle lowercase channel names
    const map: Record<string, ChannelType> = {
      slack: ChannelType.SLACK,
      telegram: ChannelType.TELEGRAM,
      discord: ChannelType.DISCORD,
      whatsapp: ChannelType.WHATSAPP,
      imessage: ChannelType.IMESSAGE,
      email: ChannelType.EMAIL,
    };
    ct = map[channel.toLowerCase()] || ct;
  } catch {
    return res.status(400).json({ error: `Unknown channel: ${channel}` });
  }

  try {
    const adapter = getAdapter(ct);
    const msg = adapter.normalize(req.body);

    if (!msg) {
      // Slack URL verification challenge
      if (req.body.challenge) return res.json({ challenge: req.body.challenge });
      // Discord interaction ping
      if (req.body.type === 1) return res.json({ type: 1 });
      return res.json({ status: "ignored" });
    }

    // Check for unsupported image attachments
    if (msg.attachments.some((a) => a.type === "image")) {
      const base = adapter as any;
      const response = base.imageNotSupported(
        msg.attachments[0].name,
        process.env.ORCHESTRA_MODEL || "nemotron-mini"
      );
      await adapter.send(msg.senderId, response, msg.threadId);
      return res.json({ status: "image_rejected", response });
    }

    // Route to Orchestra
    const base = adapter as any;
    const taskId = await base.routeToOrchestra(ORCHESTRA_API_URL, msg);
    const response = await base.waitForResponse(ORCHESTRA_API_URL, taskId);

    // Send response back to the channel
    await adapter.send(msg.senderId, response, msg.threadId);

    res.json({ status: "ok", channel, response: response.slice(0, 200) });
  } catch (e) {
    console.error(`[${channel}] Error:`, e);
    res.status(500).json({ error: String(e) });
  }
});

// ── WhatsApp WebSocket listener ──────────────────────────

let whatsappAdapter: import("../adapters/whatsapp").WhatsAppAdapter | null = null;

app.post("/whatsapp/start", async (_req, res) => {
  try {
    const { WhatsAppAdapter } = await import("../adapters/whatsapp");
    whatsappAdapter = new WhatsAppAdapter();

    whatsappAdapter.listen(async (msg: InboundMessage) => {
      const wa = whatsappAdapter! as any;

      // Check image support
      if (msg.attachments.some((a) => a.type === "image")) {
        const response = wa.imageNotSupported(
          msg.attachments[0].name,
          process.env.ORCHESTRA_MODEL || "nemotron-mini"
        );
        await wa.send(msg.senderId, response, msg.threadId);
        return;
      }

      // Route to Orchestra and respond
      const taskId = await wa.routeToOrchestra(ORCHESTRA_API_URL, msg);
      const response = await wa.waitForResponse(ORCHESTRA_API_URL, taskId);
      await wa.send(msg.senderId, response, msg.threadId);
    });

    res.json({ status: "whatsapp_started" });
  } catch (e) {
    res.status(500).json({ error: String(e) });
  }
});

app.get("/whatsapp/qr", (_req, res) => {
  const qr = whatsappAdapter?.getQR();
  if (!qr) return res.json({ status: "no_qr_yet" });
  res.json({ qr });
});

// ── Start server ─────────────────────────────────────────

app.listen(PORT, () => {
  console.log(`[Orchestra Channels] running on http://0.0.0.0:${PORT}`);
  console.log(`[Orchestra Channels] Routing to Orchestra API: ${ORCHESTRA_API_URL}`);
  console.log(`[Orchestra Channels] Adapters: ${listAdapters().map((c) => c.toString()).join(", ")}`);
});
