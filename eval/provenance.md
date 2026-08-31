# Final Evaluation Provenance

This document records the exact state of the artifacts used for the Day 11 final evaluation to guarantee reproducibility and prevent tampering.

## Commit State
- **`evaluation_commit`**: `6abe7f8c6ce4a0ef25cc978c0c071505d6bc9419`

## Artifact SHA-256 Hashes
| Artifact | Path | SHA-256 |
|---|---|---|
| Production Model | `models/xgboost_rto_v1.bin` | `9490755886c736eafab5a0cb943e9262c0b7d95d396c1d56be6910b2227505be` |
| Evaluation Data | `data/heldout.csv` | `a150979d9a755342f659147842a5f82ba3f46058291882d35cdffdf0ae0196a3` |
| Threshold Config | `config/thresholds.json` | `753006e95f94b1281ded28294df330769f875f9da0d7f22276f31205fa973653` |
| Training Data | `data/train.csv` | `ad901b61c7e32b9a1556ceb2545ba33bfb86b31c466fb32610e1ec5e7c57ade2` |
| Validation Data | `data/val.csv` | `ddfc7f31d6b9c03266bd7fdcadb43a1872d956e14af3dcb503e88225f2d50f11` |

## Integrity Verification
The evaluation generated the following core metrics, completely isolated from training data and driven strictly by the frozen thresholds `[0.50, 0.75]`:
- **Estimated Net Saved**: ₹15,611
- **Precision**: 87.1%
- **Recall**: 80.4%
- **Confusion Matrix**: TP=148 (RTO correctly flagged), FP=22 (Legitimate inconvenienced)
- **Estimated Net Saved (Drifted Subset)**: ₹2,507
