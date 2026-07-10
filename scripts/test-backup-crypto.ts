import assert from 'node:assert/strict';

import { decryptBackupData, encryptBackupData } from '../src/lib/backup-crypto';

const passphrase = 'correct horse battery staple';
const source = JSON.stringify({ version: 4, conversations: [{ id: 'case-1', title: '合同纠纷' }] });

const encrypted = await encryptBackupData(source, passphrase);
const roundTrip = await decryptBackupData(encrypted, passphrase);
assert.equal(roundTrip.data, source);
assert.equal(roundTrip.format, 'aes-gcm-v2');

await assert.rejects(() => decryptBackupData(encrypted, 'incorrect passphrase value'), /口令错误|完整性/);

const envelope = JSON.parse(new TextDecoder().decode(encrypted));
const ciphertext = Uint8Array.from(atob(envelope.ciphertext), character => character.charCodeAt(0));
ciphertext[Math.floor(ciphertext.length / 2)] ^= 1;
envelope.ciphertext = btoa(String.fromCharCode(...ciphertext));
const tampered = new TextEncoder().encode(JSON.stringify(envelope));
await assert.rejects(() => decryptBackupData(tampered, passphrase), /口令错误|完整性/);

const legacyKey = 'Lawver-Security-Migration-Key-2024';
const legacy = new TextEncoder().encode(source);
for (let index = 0; index < legacy.length; index += 1) {
  legacy[index] ^= legacyKey.charCodeAt(index % legacyKey.length);
}
const migrated = await decryptBackupData(legacy, '');
assert.equal(migrated.data, source);
assert.equal(migrated.format, 'legacy-xor');

console.log('backup crypto: round-trip, wrong-password, tamper, and legacy migration checks passed');
