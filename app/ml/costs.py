class CostEngine:
    def __init__(self, c_rto=150, c_fp_m=40, c_fp_h=400, gamma_m=0.25, gamma_h=0.45, d=50, v=15, rho=0.10):
        self.c_rto = c_rto
        self.c_fp_m = c_fp_m
        self.c_fp_h = c_fp_h
        self.gamma_m = gamma_m
        self.gamma_h = gamma_h
        self.d = d
        self.v = v
        self.rho = rho
        
    def cost_fn(self):
        return self.c_rto
        
    def cost_tp_m(self):
        return self.gamma_m * self.d + (1 - self.gamma_m) * self.c_rto
        
    def cost_fp_m(self):
        return self.gamma_m * self.d + (1 - self.gamma_m) * self.c_fp_m
        
    def cost_tp_h_confirmed(self):
        return self.v + self.rho * self.c_rto

    def cost_tp_h_abandoned(self):
        # 0 freight loss for canceled high-risk COD orders
        return 0

    def cost_tp_h(self):
        return self.gamma_h * self.cost_tp_h_confirmed() + (1 - self.gamma_h) * self.cost_tp_h_abandoned()
        
    def cost_fp_h(self):
        return (1 - self.gamma_h) * self.c_fp_h + self.gamma_h * self.v
        
    def evaluate_decisions(self, y_true, y_pred_tier):
        """
        Evaluate net saved for a list of truths and tier decisions.
        y_true: array of actual RTO (1) or not (0)
        y_pred_tier: array of 'ALLOW_COD', 'NUDGE_PREPAY', 'SOFT_GATE_COD'
        """
        baseline_loss = sum(y_true) * self.c_rto
        engine_loss = 0
        
        for yt, yp in zip(y_true, y_pred_tier):
            if yp == 'ALLOW_COD':
                if yt == 1:
                    engine_loss += self.cost_fn()
            elif yp == 'NUDGE_PREPAY':
                if yt == 1:
                    engine_loss += self.cost_tp_m()
                else:
                    engine_loss += self.cost_fp_m()
            elif yp == 'SOFT_GATE_COD':
                if yt == 1:
                    engine_loss += self.cost_tp_h()
                else:
                    engine_loss += self.cost_fp_h()
                    
        net_saved = baseline_loss - engine_loss
        return net_saved

def compute_breakeven_ratios(engine=None):
    if engine is None:
        engine = CostEngine()
    
    # M-Tier breakeven: Net incremental gain of TP = Net incremental penalty of FP
    # Gain(TP_M) = Cost(FN) - Cost(TP_M)
    gain_tp_m = engine.cost_fn() - engine.cost_tp_m()
    # Penalty(FP_M) = Cost(FP_M) - Cost(TN)
    penalty_fp_m = engine.cost_fp_m()
    # TP / FP = penalty / gain
    m_ratio = penalty_fp_m / gain_tp_m if gain_tp_m > 0 else float('inf')

    # H-Tier breakeven: Net incremental gain of TP = Net incremental penalty of FP
    # Gain(TP_H) = Cost(FN) - Cost(TP_H)
    gain_tp_h = engine.cost_fn() - engine.cost_tp_h()
    # Penalty(FP_H) = Cost(FP_H)
    penalty_fp_h = engine.cost_fp_h()
    
    h_ratio = penalty_fp_h / gain_tp_h if gain_tp_h > 0 else float('inf')
    
    return m_ratio, h_ratio
