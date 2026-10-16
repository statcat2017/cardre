/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DATASET_UPLOAD_TIMEOUT_MS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
