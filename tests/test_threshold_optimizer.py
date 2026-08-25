import pytest
from app.ml.costs import CostEngine, compute_breakeven_ratios
import pandas as pd
import numpy as np

def test_cost_tp_h_no_c_rto_term():
    """
    Test asserting the canceled-high-risk branch literally evaluates to a cost with NO C_RTO term.
    """
    engine1 = CostEngine(c_rto=150)
    engine2 = CostEngine(c_rto=999999)
    
    # The abandoned branch should not scale with C_RTO
    assert engine1.cost_tp_h_abandoned() == engine2.cost_tp_h_abandoned()
    assert engine1.cost_tp_h_abandoned() == 0

def test_breakeven_ratios():
    m_ratio, h_ratio = compute_breakeven_ratios()
    # M-Tier breakeven = 1.700
    assert abs(m_ratio - 1.700) < 0.001
    # H-Tier breakeven = 1.661
    assert abs(h_ratio - 1.661) < 0.002

def test_breakeven_ratios_exact():
    engine = CostEngine()
    gain_tp_m = engine.cost_fn() - engine.cost_tp_m()
    # 150 - (0.25 * 50 + 0.75 * 150) = 150 - (12.5 + 112.5) = 150 - 125 = 25
    assert gain_tp_m == 25.0
    
    m_ratio, h_ratio = compute_breakeven_ratios(engine)
    assert m_ratio == 42.50 / 25.0 # 1.7
    
    gain_tp_h = engine.cost_fn() - engine.cost_tp_h()
    # 150 - 0.45 * (15 + 15) = 150 - 13.5 = 136.5
    assert gain_tp_h == 136.5
    
    assert abs(h_ratio - (226.75 / 136.5)) < 0.001

def test_evaluate_decisions_outperforms_baseline():
    engine = CostEngine()
    
    # 10 true positives, 10 true negatives
    y_true = [1]*10 + [0]*10
    
    # Do nothing baseline
    y_pred_baseline = ['ALLOW_COD']*20
    net_saved_baseline = engine.evaluate_decisions(y_true, y_pred_baseline)
    assert net_saved_baseline == 0
    
    # Perfect routing:
    # TP (actual RTO) -> routed to NUDGE or GATE
    # TN (actual not RTO) -> routed to ALLOW
    y_pred_perfect = ['SOFT_GATE_COD']*10 + ['ALLOW_COD']*10
    net_saved_perfect = engine.evaluate_decisions(y_true, y_pred_perfect)
    
    assert net_saved_perfect > 0
