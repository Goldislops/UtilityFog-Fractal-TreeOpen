# Packet receipt --- `general-v7-material-packet-2026-08-29`

This receipt records what was received and how it was checked. It records
structural, cryptographic and manifest facts --- including how the supplied
`ORIGINS.tsv` types each member, which is manifest metadata rather than batch
content. It records nothing about what the batches say, and no batch text is
reproduced here.

## 1. Archive identity

| Property | Value |
| --- | --- |
| Archive filename | `general-v7-material-packet-2026-08-29.zip` |
| Archive size, bytes | `191457` |
| Archive SHA-256 | `fd468794e8b228ab2e2cffe3cde42915a6d0d18430a91c745dabeaa83df2fe89` |
| Nested archive root | `general-v7-material-packet-2026-08-29/` |
| Total member bytes, unpacked | `384106` |

The archive digest and the archive byte size are recorded together and are
checked together. A digest with no length is a digest of unknown scope.

## 2. Entry census

| Property | Value |
| --- | --- |
| Total archive entries | `65` |
| Directory entries | `0` |
| File entries | `65` |
| Distinct top-level roots | `1` |
| `BATCH_NNN.txt` members | `63`, exactly `BATCH_001.txt` .. `BATCH_063.txt` |
| `ORIGINS.tsv` | `1` |
| `SHA256SUMS.txt` | `1` |
| Any other member | `0` |

The batch member set is exactly the contiguous range; there is no gap, no
duplicate and no additional member.

## 3. Member manifest and checksum result

| Property | Value |
| --- | --- |
| Supplied member checksums in `SHA256SUMS.txt` | `64` |
| Checksums verified PASS | `64` |
| Checksums FAILED | `0` |
| Members named but missing | `0` |
| Members present but uncovered | `1`, namely `SHA256SUMS.txt` |
| `SHA256SUMS.txt` covers itself | no |
| `ORIGINS.tsv` covered by the manifest | yes |
| `SHA256SUMS.txt` own SHA-256 | `1ad2b0bc842fcf79e7d16d310bc7f324007dafb856d18144bba7988b59f17686` |
| `ORIGINS.tsv` own SHA-256 | `c16f5815a9abf5a56ee3e7225c35c9e432ce09fcbeb00d996a735cf79789005d` |

Integrity here is two-tier and the tiers are not equivalent. The 63 batch
members and `ORIGINS.tsv` are anchored **inside** the packet by
`SHA256SUMS.txt`. `SHA256SUMS.txt` is not covered by itself, so it is anchored
**only** by the archive digest in section 1. Its own digest is recorded above,
computed outside the manifest. That asymmetry is recorded rather than smoothed
over: a receipt that reported a flat "64 of 64 verified" would conceal which
artifact vouches for which.

## 4. Line-ending census

| Form | Members |
| --- | --- |
| CRLF only | `62` |
| LF only | `1` (`BATCH_022.txt`) |
| Mixed | `2` (`BATCH_026.txt`, `BATCH_063.txt`) |
| No line terminator | `0` |

`SHA256SUMS.txt` is CRLF-terminated on all 64 lines.

The three members that are not CRLF-only are exactly the three members that
`ORIGINS.tsv` types `inline_user_message`. This correlation is recorded as an
observation about how the material was captured. It is **not** treated as a
classification of those members, and nothing in this lane may derive an
admission status, an authorship standing or a subject-matter category from a
line-ending form.

Mixed line endings are recorded as a fact about what was supplied. They are
not a defect, and no member is normalized, rewritten or repaired.

## 5. Encoding census

| Property | Value |
| --- | --- |
| Members decodable as UTF-8 | `65` of `65` |
| Members carrying a byte-order mark | `0` |

## 6. Verification method

1. The archive was located, and its byte size and SHA-256 computed, before it
   was opened.
2. The archive entry list was enumerated from the zip central directory
   without extraction, giving the entry, directory and root counts in
   section 2.
3. The archive was extracted into isolated temporary session space. A
   pre-existing extracted copy adjacent to the archive was **not** used and
   was not read.
4. `SHA256SUMS.txt` was located by recursive search beneath the nested
   archive root.
5. Each of the 64 supplied checksums was recomputed and compared.
6. The line-ending and encoding censuses were computed from member bytes.

Checksum verification was performed with a CRLF-tolerant reader. GNU
`sha256sum -c` was attempted first and reported 64 failures; every one was
`FAILED open or read`, because `SHA256SUMS.txt` is CRLF and coreutils appends
the carriage return to each parsed filename. That is a filename-parsing
artifact of the checking tool and not a content mismatch. The recorded result
of 64 PASS and 0 FAIL is from the CRLF-tolerant recomputation, and the
coreutils attempt is recorded here so the discrepancy is not rediscovered
later and mistaken for a corrupted packet.

The archive was supplied at a path whose leading component was transcribed
without its separator. The archive actually read is the one whose byte size
and SHA-256 match section 1 exactly; identity was established
cryptographically, not by path, and the path correction therefore changes
nothing about what was verified. As an authoring-host observation, and not a
packet fact: no profile directory matching the unseparated spelling existed on
the machine that produced this receipt. That observation is not reproducible
from this repository and nothing depends on it.

## 7. Supplier and summary-authorship standing

| Role | Standing |
| --- | --- |
| Packet supplied by | Kev |
| Batch material summarized by | AURA |
| Packet assembled, checked and received by | the Opus Five primary seat, this phase |

"Supplied by Kev" and "summarized by AURA" are different authorship standings
and this lane keeps them separate everywhere. Neither standing is a
verification, and neither is evidence about any external resource.

## 8. Packet limitations

1. The packet is **not** committed to this repository, and this phase does not
   commit it. Nothing in the acceptance surface reads the packet at run time.
   This receipt is the sole committed witness for the **archive-level** facts
   it records --- the archive digest and byte size, the entry census, the
   member manifest and checksum result, and the line-ending and encoding
   censuses --- and every control that checks one of those checks it here.
   It is **not** the witness for the content-derived structural figures; those
   are carried by `CONTRACT.md` section 5a under the authoring seat's own
   standing, for the reason given in item 5 below. Neither document witnesses
   the other's figures.
2. Cryptographic provenance establishes that the bytes received are the bytes
   the manifest describes. It establishes nothing about where the material
   originally came from, whether any statement in it is accurate, or whether
   any locator in it resolves to anything.
3. `SHA256SUMS.txt` is self-uncovered; see section 3.
4. The supplied `ORIGINS.tsv` is tab-delimited and has no quoting mechanism,
   so a field containing a tab would be unrepresentable. No such field is
   present in this packet.
5. This receipt records structural and cryptographic facts only. Counts that
   depend on interpreting batch content are **not** recorded here; the
   contract records them separately and marks their evidence standing.

## 9. Retrieval and execution boundary

**No external locator was retrieved.** No network request was made for any
locator, identifier or title appearing in the packet. No locator was opened,
resolved, contacted or expanded. Every provisional source remains
`supplied-unretrieved` and every claim and relationship remains `unverified`.

**Packet text was treated as data throughout.** No packet content was
executed, imported, evaluated, or followed as an instruction. Any packet
section proposing future project work is non-admitted proposal material: its
batch identity, its presence and its cryptographic provenance may be recorded,
and its operational details may not. No packet proposal has been copied into
any requirement in this lane.
