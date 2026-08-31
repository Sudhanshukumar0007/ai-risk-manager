---
seed: 42
---
# Drift Attribution & Ablation Study

The Day 10 evaluation found the model performs exceptionally well on the drifted subset (novel pincodes/flash sales), yet the explicit drift probe features (`is_novel_pincode`, `is_flash_sale_cart_value`) had zero SHAP weight. We investigated the actual mechanism.

## SHAP Attribution on Shifted Subset
Actual average absolute SHAP values for `is_novel=1` rows:

| Feature | Mean |Abs| SHAP |
|---|---:|
| `is_cod_selected` | 2.2735 |
| `category_baseline_rto_rate` | 1.6009 |
| `customer_past_rto_count` | 0.9709 |
| `address_tfidf_ambiguity_score` | 0.9051 |
| `phone_order_velocity_7d` | 0.5638 |
| `hub_distance_km` | 0.5493 |
| `account_age_days` | 0.5430 |
| `address_char_length` | 0.3147 |
| `device_account_reuse_count` | 0.2738 |
| `cart_value_category_std_dev` | 0.1242 |
| `pincode_historical_rto_rate` | 0.0353 |
| `item_quantity_anomaly_score` | 0.0315 |
| `is_night_order` | 0.0111 |
| `is_novel_pincode` | 0.0000 |
| `is_flash_sale_cart_value` | 0.0000 |

## Ablation Test
We retrained a transient variant model excluding the two explicit drift features to confirm they aren't carrying the signal.

| Model | Estimated Net Saved on Shifted Subset |
|---|---:|
| **Full Model** (frozen production) | ₹2,507 |
| **Ablated Model** (no drift features) | ₹2,607 |

### Conclusion
The ablation model performs almost identically to the full model, confirming the explicit drift features are completely ignored. Instead, the model flags the novel pincode flash-sale orders indirectly via features like `is_cod_selected` and `category_baseline_rto_rate` which happen to be active for those rows. We cannot conclusively prove the model 'understands' the drift conceptually; it merely falls back to other high-risk indicators that correlate with it.
