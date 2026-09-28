/*
 * 模块描述：版本化会话备份加密，使用 PBKDF2 + AES-GCM，并兼容只读导入旧版 XOR 文件。
 */

const BACKUP_FORMAT = 'lawver-backup';
const BACKUP_VERSION = 2;
const KDF_ITERATIONS = 310_000;
const SALT_BYTES = 16;
const IV_BYTES = 12;
const MIN_PASSPHRASE_LENGTH = 12;
const MAX_ENCRYPTED_FILE_BYTES = 96 * 1024 * 1024;
const ADDITIONAL_DATA = new TextEncoder().encode(`${BACKUP_FORMAT}:v${BACKUP_VERSION}`);

const LEGACY_EXPORT_KEYS = [
  'Lawver-Security-Migration-Key-2024',
  'GDUT-Lawyer-Security-Migration-Key-2024',
] as const;

interface BackupEnvelopeV2 {
  format: typeof BACKUP_FORMAT;
  version: typeof BACKUP_VERSION;
  kdf: {
    name: 'PBKDF2';
    hash: 'SHA-256';
    iterations: number;
    salt: string;
  };
  cipher: {
    name: 'AES-GCM';
    iv: string;
  };
  ciphertext: string;
}

export interface DecryptedBackup {
  data: string;
  format: 'aes-gcm-v2' | 'legacy-xor';
}

const bytesToBase64 = (bytes: Uint8Array): string => {
  let binary = '';
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
  }
  return btoa(binary);
};

const base64ToBytes = (value: string, label: string): Uint8Array => {
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(value) || value.length % 4 !== 0) {
    throw new Error(`备份中的 ${label} 不是合法 Base64。`);
  }
  try {
    const binary = atob(value);
    return Uint8Array.from(binary, character => character.charCodeAt(0));
  } catch {
    throw new Error(`备份中的 ${label} 不是合法 Base64。`);
  }
};

const getCrypto = (): Crypto => {
  const cryptoApi = globalThis.crypto;
  if (!cryptoApi?.subtle || !cryptoApi.getRandomValues) {
    throw new Error('当前环境不支持安全备份加密，请使用 HTTPS、localhost 或原生客户端。');
  }
  return cryptoApi;
};

const normalizePassphrase = (passphrase: string): string => {
  const normalized = passphrase.normalize('NFKC');
  if (normalized.length < MIN_PASSPHRASE_LENGTH) {
    throw new Error(`备份口令至少需要 ${MIN_PASSPHRASE_LENGTH} 个字符。`);
  }
  return normalized;
};

const deriveBackupKey = async (passphrase: string, salt: Uint8Array): Promise<CryptoKey> => {
  const cryptoApi = getCrypto();
  const keyMaterial = await cryptoApi.subtle.importKey(
    'raw',
    new TextEncoder().encode(normalizePassphrase(passphrase)),
    'PBKDF2',
    false,
    ['deriveKey'],
  );
  return cryptoApi.subtle.deriveKey(
    {
      name: 'PBKDF2',
      hash: 'SHA-256',
      salt,
      iterations: KDF_ITERATIONS,
    },
    keyMaterial,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  );
};

const parseEnvelope = (value: unknown): BackupEnvelopeV2 | null => {
  if (!value || typeof value !== 'object') return null;
  const candidate = value as Partial<BackupEnvelopeV2>;
  if (candidate.format !== BACKUP_FORMAT) return null;
  if (candidate.version !== BACKUP_VERSION) {
    throw new Error(`不支持的备份版本：${String(candidate.version ?? '未知')}。`);
  }
  if (
    candidate.kdf?.name !== 'PBKDF2'
    || candidate.kdf.hash !== 'SHA-256'
    || candidate.kdf.iterations !== KDF_ITERATIONS
    || typeof candidate.kdf.salt !== 'string'
    || candidate.cipher?.name !== 'AES-GCM'
    || typeof candidate.cipher.iv !== 'string'
    || typeof candidate.ciphertext !== 'string'
  ) {
    throw new Error('备份加密参数无效或已损坏。');
  }
  return candidate as BackupEnvelopeV2;
};

const decodeLegacyBackup = (source: Uint8Array): string | null => {
  for (const key of LEGACY_EXPORT_KEYS) {
    const bytes = new Uint8Array(source);
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] ^= key.charCodeAt(index % key.length);
    }
    const decoded = new TextDecoder().decode(bytes);
    try {
      JSON.parse(decoded);
      return decoded;
    } catch {
      // Try the next historical key.
    }
  }
  return null;
};

export const encryptBackupData = async (data: string, passphrase: string): Promise<Uint8Array> => {
  JSON.parse(data);
  const cryptoApi = getCrypto();
  const salt = cryptoApi.getRandomValues(new Uint8Array(SALT_BYTES));
  const iv = cryptoApi.getRandomValues(new Uint8Array(IV_BYTES));
  const key = await deriveBackupKey(passphrase, salt);
  const ciphertext = await cryptoApi.subtle.encrypt(
    { name: 'AES-GCM', iv, additionalData: ADDITIONAL_DATA, tagLength: 128 },
    key,
    new TextEncoder().encode(data),
  );
  const envelope: BackupEnvelopeV2 = {
    format: BACKUP_FORMAT,
    version: BACKUP_VERSION,
    kdf: {
      name: 'PBKDF2',
      hash: 'SHA-256',
      iterations: KDF_ITERATIONS,
      salt: bytesToBase64(salt),
    },
    cipher: {
      name: 'AES-GCM',
      iv: bytesToBase64(iv),
    },
    ciphertext: bytesToBase64(new Uint8Array(ciphertext)),
  };
  return new TextEncoder().encode(JSON.stringify(envelope));
};

export const decryptBackupData = async (
  source: Uint8Array,
  passphrase: string,
): Promise<DecryptedBackup> => {
  if (source.byteLength > MAX_ENCRYPTED_FILE_BYTES) {
    throw new Error('备份文件过大，已拒绝导入。');
  }

  const text = new TextDecoder().decode(source);
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    const legacy = decodeLegacyBackup(source);
    if (legacy !== null) return { data: legacy, format: 'legacy-xor' };
    throw new Error('备份格式无效或文件已损坏。');
  }

  const envelope = parseEnvelope(parsed);
  if (!envelope) {
    const legacy = decodeLegacyBackup(source);
    if (legacy !== null) return { data: legacy, format: 'legacy-xor' };
    throw new Error('备份格式无效或文件已损坏。');
  }

  const salt = base64ToBytes(envelope.kdf.salt, 'salt');
  const iv = base64ToBytes(envelope.cipher.iv, 'iv');
  const ciphertext = base64ToBytes(envelope.ciphertext, 'ciphertext');
  if (salt.byteLength !== SALT_BYTES || iv.byteLength !== IV_BYTES) {
    throw new Error('备份加密参数长度无效。');
  }
  const key = await deriveBackupKey(passphrase, salt);
  try {
    const plaintext = await getCrypto().subtle.decrypt(
      { name: 'AES-GCM', iv, additionalData: ADDITIONAL_DATA, tagLength: 128 },
      key,
      ciphertext,
    );
    const data = new TextDecoder('utf-8', { fatal: true }).decode(plaintext);
    JSON.parse(data);
    return { data, format: 'aes-gcm-v2' };
  } catch {
    throw new Error('备份口令错误，或文件完整性校验失败。');
  }
};

export const backupPassphraseMinLength = MIN_PASSPHRASE_LENGTH;
