import * as decoding from "lib0/decoding";
import * as encoding from "lib0/encoding";
import { Awareness, applyAwarenessUpdate, encodeAwarenessUpdate } from "y-protocols/awareness";
import * as syncProtocol from "y-protocols/sync";
import * as Y from "yjs";

const messageSync = 0;
const messageAwareness = 1;

export type Annotation = {
  id: string;
  page: number;
  type: string;
  x: number;
  y: number;
  text: string;
};

export type Presence = {
  clientId: number;
  name: string;
  page: number;
};

type Connection = {
  doc: Y.Doc;
  awareness: Awareness;
  socket: WebSocket;
  annotations: Y.Array<Y.Map<string | number>>;
};

function send(socket: WebSocket, bytes: Uint8Array): void {
  if (socket.readyState === WebSocket.OPEN) socket.send(bytes);
}

function readFrame(frame: Uint8Array, doc: Y.Doc, awareness: Awareness, socket: WebSocket): void {
  const decoder = decoding.createDecoder(frame);
  const messageType = decoding.readVarUint(decoder);
  if (messageType === messageSync) {
    const encoder = encoding.createEncoder();
    encoding.writeVarUint(encoder, messageSync);
    syncProtocol.readSyncMessage(decoder, encoder, doc, "remote");
    if (encoding.length(encoder) > 1) send(socket, encoding.toUint8Array(encoder));
    return;
  }
  if (messageType === messageAwareness) {
    applyAwarenessUpdate(awareness, decoding.readVarUint8Array(decoder), "remote");
  }
}

function sendSyncStep1(socket: WebSocket, doc: Y.Doc): void {
  const encoder = encoding.createEncoder();
  encoding.writeVarUint(encoder, messageSync);
  syncProtocol.writeSyncStep1(encoder, doc);
  send(socket, encoding.toUint8Array(encoder));
}

export function connectCollaboration(options: {
  documentId: string;
  ticket: string;
  name: string;
  onStatus: (status: string, canEdit: boolean) => void;
  onAnnotations: (annotations: Annotation[]) => void;
  onPresence: (presence: Presence[]) => void;
  onSynced?: () => void;
}): { doc: Y.Doc; disconnect: () => void; addNote: (page: number, text: string) => void } {
  const doc = new Y.Doc();
  const awareness = new Awareness(doc);
  const annotations = doc.getArray<Y.Map<string | number>>("annotations");
  const url = new URL(`/api/v1/collaboration/${options.documentId}`, window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(url.toString());
  socket.binaryType = "arraybuffer";
  let canEdit = false;
  let synced = false;
  let closedByUs = false;
  const pending: Uint8Array[] = [];
  const syncTimer = window.setTimeout(() => {
    synced = true;
    options.onSynced?.();
    flush();
  }, 1500);

  function flush(): void {
    if (!canEdit || !synced || socket.readyState !== WebSocket.OPEN) return;
    for (const update of pending.splice(0)) {
      const encoder = encoding.createEncoder();
      encoding.writeVarUint(encoder, messageSync);
      syncProtocol.writeUpdate(encoder, update);
      send(socket, encoding.toUint8Array(encoder));
    }
  }

  const publishAnnotations = () => {
    const rows: Annotation[] = annotations.toArray().map((item) => ({
      id: String(item.get("id") ?? ""),
      page: Number(item.get("page") ?? 1),
      type: String(item.get("type") ?? "text"),
      x: Number(item.get("x") ?? 0),
      y: Number(item.get("y") ?? 0),
      text: String(item.get("text") ?? ""),
    }));
    options.onAnnotations(rows);
  };

  const publishPresence = () => {
    const rows: Presence[] = [];
    awareness.getStates().forEach((state, clientId) => {
      const name = typeof state.name === "string" ? state.name : "";
      if (!name) return;
      rows.push({ clientId, name, page: Number(state.page ?? 1) });
    });
    options.onPresence(rows);
  };

  annotations.observe(publishAnnotations);
  awareness.on("change", publishPresence);
  doc.on("update", (update: Uint8Array, origin: unknown) => {
    if (origin === "remote") return;
    if (!canEdit || !synced || socket.readyState !== WebSocket.OPEN) {
      pending.push(update);
      return;
    }
    const encoder = encoding.createEncoder();
    encoding.writeVarUint(encoder, messageSync);
    syncProtocol.writeUpdate(encoder, update);
    send(socket, encoding.toUint8Array(encoder));
  });
  awareness.on("update", ({ added, updated, removed }: { added: number[]; updated: number[]; removed: number[] }, origin: unknown) => {
    if (origin === "remote") return;
    const changed = added.concat(updated, removed);
    const encoder = encoding.createEncoder();
    encoding.writeVarUint(encoder, messageAwareness);
    encoding.writeVarUint8Array(encoder, encodeAwarenessUpdate(awareness, changed));
    send(socket, encoding.toUint8Array(encoder));
  });

  socket.onopen = () => socket.send(JSON.stringify({ type: "auth", ticket: options.ticket }));
  socket.onmessage = (event) => {
    if (typeof event.data === "string") {
      const message = JSON.parse(event.data) as { type?: string; canEdit?: boolean; role?: string };
      if (message.type === "auth_ok") {
        canEdit = Boolean(message.canEdit);
        options.onStatus(message.role ?? "viewer", canEdit);
        awareness.setLocalState({ name: options.name, page: 1 });
        sendSyncStep1(socket, doc);
        publishAnnotations();
        flush();
      }
      return;
    }
    const frame = new Uint8Array(event.data as ArrayBuffer);
    const probe = decoding.createDecoder(frame);
    const messageType = decoding.readVarUint(probe);
    const syncType = messageType === messageSync ? decoding.readVarUint(probe) : -1;
    readFrame(frame, doc, awareness, socket);
    if (syncType === 1 || syncType === 2) {
      synced = true;
      window.clearTimeout(syncTimer);
      options.onSynced?.();
      flush();
    }
    publishAnnotations();
  };
  socket.onerror = () => {
    if (!closedByUs) options.onStatus("disconnected", false);
  };
  socket.onclose = () => {
    if (!closedByUs) options.onStatus("disconnected", false);
  };

  const connection: Connection = { doc, awareness, socket, annotations };
  return {
    doc,
    disconnect: () => {
      closedByUs = true;
      window.clearTimeout(syncTimer);
      awareness.setLocalState(null);
      connection.socket.close();
    },
    addNote: (page: number, text: string) => {
      if (!canEdit || !text.trim()) return;
      const item = new Y.Map<string | number>();
      item.set("id", crypto.randomUUID());
      item.set("page", page);
      item.set("type", "text");
      item.set("x", 8);
      item.set("y", 8 + annotations.length * 18);
      item.set("text", text.trim());
      annotations.push([item]);
    },
  };
}
