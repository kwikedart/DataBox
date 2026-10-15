declare module "lib0/decoding" {
  export function createDecoder(data: Uint8Array): unknown;
  export function readVarUint(decoder: unknown): number;
  export function readVarUint8Array(decoder: unknown): Uint8Array;
}

declare module "lib0/encoding" {
  export function createEncoder(): unknown;
  export function writeVarUint(encoder: unknown, value: number): void;
  export function writeVarUint8Array(encoder: unknown, value: Uint8Array): void;
  export function toUint8Array(encoder: unknown): Uint8Array;
  export function length(encoder: unknown): number;
}

declare module "y-protocols/sync" {
  export function readSyncMessage(decoder: unknown, encoder: unknown, doc: unknown, origin: unknown): number;
  export function writeSyncStep1(encoder: unknown, doc: unknown): void;
  export function writeUpdate(encoder: unknown, update: Uint8Array): void;
}

declare module "y-protocols/awareness" {
  export class Awareness {
    constructor(doc: unknown);
    setLocalState(state: { name: string; page: number } | null): void;
    getStates(): Map<number, { name?: string; page?: number }>;
    on(
      event: "change",
      handler: () => void,
    ): void;
    on(
      event: "update",
      handler: (
        changes: { added: number[]; updated: number[]; removed: number[] },
        origin: unknown,
      ) => void,
    ): void;
  }
  export function applyAwarenessUpdate(awareness: Awareness, update: Uint8Array, origin: unknown): void;
  export function encodeAwarenessUpdate(awareness: Awareness, clients: number[]): Uint8Array;
}
