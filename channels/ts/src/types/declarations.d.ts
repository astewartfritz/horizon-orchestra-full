declare module "node-fetch" {
  const fetch: any;
  export default fetch;
}

declare module "eventsource" {
  export default class EventSource {
    constructor(url: string);
    onopen: ((event: any) => void) | null;
    onmessage: ((event: any) => void) | null;
    onerror: ((event: any) => void) | null;
    close(): void;
    readyState: number;
    static CONNECTING: number;
    static OPEN: number;
    static CLOSED: number;
  }
}

declare module "whatsapp-web.js" {
  export class Client {
    constructor(options: any);
    on(event: string, cb: (...args: any[]) => void): void;
    initialize(): Promise<void>;
  }
  export class LocalAuth {
    constructor();
  }
}

declare module "nodemailer" {
  export function createTransport(config: any): any;
}

declare module "imap" {
  const Imap: any;
  export default Imap;
}
