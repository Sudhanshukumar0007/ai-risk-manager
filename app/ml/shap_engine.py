import os
import joblib
import shap
import pandas as pd

# Load the model at module level to avoid reloading on every request
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MODEL_PATH = os.path.join(BASE_DIR, "models", "xgboost_rto_v1.base.bin")

_xgb_model = None
_explainer = None

def _get_explainer():
    global _xgb_model, _explainer
    if _explainer is None:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(f"Model file not found at {MODEL_PATH}")
        
        _xgb_model = joblib.load(MODEL_PATH)
            
        # Initialize TreeExplainer
        _explainer = shap.TreeExplainer(_xgb_model)
        
    return _explainer

def explain_prediction(features_dict: dict) -> list:
    """
    Given a dictionary of exactly the 15 features used for training,
    returns the top-3 feature attributions as a list of dicts.
    
    Example output:
    [
        {"feature": "cart_value_category_std_dev", "impact": 0.45},
        {"feature": "is_night_order", "impact": 0.12},
        {"feature": "pincode_historical_rto_rate", "impact": -0.08}
    ]
    """
    explainer = _get_explainer()
    
    # Must order the features in the exact same order as training
    # We can infer it from the model's feature names if available,
    # or rely on a hardcoded list. XGBoost usually remembers feature names
    # if it was trained on a DataFrame.
    
    # Converting dict to single-row DataFrame ensures we have column names
    # matching the dictionary keys.
    df = pd.DataFrame([features_dict])
    
    # SHAP expects the DataFrame columns to match exactly what it saw during training
    # For safety, let's extract the feature names the model expects
    if hasattr(_xgb_model, 'feature_names_in_'):
        feature_cols = list(_xgb_model.feature_names_in_)
        # Reorder df columns just in case
        df = df[feature_cols]
    else:
        feature_cols = list(df.columns)
        
    # Calculate SHAP values
    shap_values = explainer.shap_values(df)
    
    # shap_values is a numpy array of shape (1, num_features)
    # Get the values for this single instance
    instance_shap = shap_values[0]
    
    # Map feature names to their shap values
    feature_impacts = []
    for i, col in enumerate(feature_cols):
        feature_impacts.append({
            "feature": col,
            "impact": float(instance_shap[i])
        })
        
    # Sort by absolute impact (descending)
    feature_impacts.sort(key=lambda x: abs(x["impact"]), reverse=True)
    
    # Return Top 3
    return feature_impacts[:3]
