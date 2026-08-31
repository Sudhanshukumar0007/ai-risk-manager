# Dataset & Config Isolation Verification

To ensure statistical honesty and strict blind evaluation, the datasets and threshold configuration were frozen at Day 5. This report provides the machine-verifiable cryptographic proof of that isolation.

## SHA-256 Hashes
| File | Expected Hash (Day 5 Freeze) | Actual Hash | Match |
|---|---|---|---|
| `train.csv` | `ad901b61c7e32b9a1556ceb2545ba33bfb86b31c466fb32610e1ec5e7c57ade2` | `ad901b61c7e32b9a1556ceb2545ba33bfb86b31c466fb32610e1ec5e7c57ade2` | ✅ |
| `val.csv` | `ddfc7f31d6b9c03266bd7fdcadb43a1872d956e14af3dcb503e88225f2d50f11` | `ddfc7f31d6b9c03266bd7fdcadb43a1872d956e14af3dcb503e88225f2d50f11` | ✅ |
| `heldout.csv` | `a150979d9a755342f659147842a5f82ba3f46058291882d35cdffdf0ae0196a3` | `a150979d9a755342f659147842a5f82ba3f46058291882d35cdffdf0ae0196a3` | ✅ |
| `thresholds.json` | `753006e95f94b1281ded28294df330769f875f9da0d7f22276f31205fa973653` | `753006e95f94b1281ded28294df330769f875f9da0d7f22276f31205fa973653` | ✅ |

## Verification Status
Status: ✅ **PASSED**. Zero modifications detected since freeze. Blind evaluation protocol preserved.
