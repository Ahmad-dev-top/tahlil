export interface SseEvent {
  event: string;
  data: string;
}

/**
 * Incremental Server-Sent Events parser. Feed it text chunks split anywhere;
 * it returns the events completed by that chunk. Pure, so it is unit-tested.
 */
export class SseParser {
  private buffer = "";
  private event = "message";
  private data: string[] = [];

  push(chunk: string): SseEvent[] {
    this.buffer += chunk;
    const out: SseEvent[] = [];
    let m: RegExpExecArray | null;
    while ((m = /\r\n|\r|\n/.exec(this.buffer))) {
      // a trailing "\r" may be the first half of "\r\n" split across chunks: wait for more
      if (m[0] === "\r" && m.index === this.buffer.length - 1) break;
      const line = this.buffer.slice(0, m.index);
      this.buffer = this.buffer.slice(m.index + m[0].length);
      const ev = this.line(line);
      if (ev) out.push(ev);
    }
    return out;
  }

  /** Call when the stream ends, to flush an event that had no trailing blank line. */
  end(): SseEvent[] {
    const out: SseEvent[] = [];
    if (this.buffer) {
      const ev = this.line(this.buffer);
      if (ev) out.push(ev);
      this.buffer = "";
    }
    const ev = this.line("");
    if (ev) out.push(ev);
    return out;
  }

  private line(line: string): SseEvent | null {
    if (line === "") {
      if (!this.data.length) return null;
      const ev = { event: this.event, data: this.data.join("\n") };
      this.event = "message";
      this.data = [];
      return ev;
    }
    if (line.startsWith(":")) return null; // comment / keep-alive
    const i = line.indexOf(":");
    const field = i === -1 ? line : line.slice(0, i);
    let value = i === -1 ? "" : line.slice(i + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") this.event = value;
    else if (field === "data") this.data.push(value);
    return null;
  }
}
